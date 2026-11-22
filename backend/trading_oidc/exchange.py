"""Bounded single-send OIDC code exchange; no routes, attempts or session authority."""

import asyncio
import math
import re
import threading
import time
from collections.abc import AsyncGenerator, AsyncIterator, Callable
from dataclasses import dataclass
from typing import Literal, Protocol, cast

import httpx2 as httpx
from authlib.oauth2.auth import ClientAuth  # type: ignore[import-untyped]
from authlib.oauth2.rfc6749.parameters import prepare_token_request  # type: ignore[import-untyped]
from pydantic import SecretStr

from trading_auth.models import AuthenticationDenied, AuthenticationUnavailable
from trading_oidc.callback import ParsedCallback, check_callback_binding
from trading_oidc.contracts import MAX_TIMESTAMP, LoginAttempt, OidcClient
from trading_oidc.verification import MAX_TOKEN_BYTES, _object

REQUEST_SECONDS = 10
MAX_RESPONSE_BYTES = 65536
MAX_REQUEST_BYTES = 8192
_CLEANUP_SECONDS = 3
_IO_SECONDS = 3
_CHUNK_BYTES = 4096
_MAX_HEADERS = 64
_MAX_HEADER_BYTES = 16384


@dataclass(frozen=True, repr=False)
class ClientSecretAuthentication:
    """Trusted in-memory credential; no loading, persistence or method negotiation."""

    secret: SecretStr
    method: Literal["client_secret_basic"] = "client_secret_basic"

    def __post_init__(self) -> None:
        if (
            type(self.secret) is not SecretStr
            or type(self.method) is not str
            or self.method != "client_secret_basic"
            or re.fullmatch(r"[A-Za-z0-9_-]{43,128}", self.secret.get_secret_value(), re.ASCII)
            is None
        ):
            raise AuthenticationUnavailable() from None


class UnverifiedTokenResponse(Protocol):
    """Secret protocol output only; no identity, owner or browser-session authority."""

    @property
    def id_token(self) -> SecretStr: ...

    @property
    def access_token(self) -> SecretStr: ...

    @property
    def expires_in(self) -> int | None: ...


@dataclass(frozen=True, repr=False)
class _TokenResponse:
    id_token: SecretStr
    access_token: SecretStr
    expires_in: int | None


class _PrepareTokenRequest(Protocol):
    def __call__(
        self, grant_type: str, *, redirect_uri: str, code: str, code_verifier: str
    ) -> str: ...


class _ClientAuthentication(Protocol):
    def prepare(
        self, method: str, uri: str, headers: dict[str, str], body: str
    ) -> tuple[str, dict[str, str], str]: ...


_prepare_token_request = cast(_PrepareTokenRequest, prepare_token_request)
_client_authentication = cast(Callable[[str, str, str], _ClientAuthentication], ClientAuth)


class _NetworkGate:
    """Separate exchange custody; it does not replace or widen the JWKS gate."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._busy = False
        self._disabled = False

    def acquire(self) -> None:
        with self._lock:
            if self._busy or self._disabled:
                raise AuthenticationUnavailable() from None
            self._busy = True

    def release(self) -> None:
        with self._lock:
            self._busy = False

    def disable(self) -> None:
        with self._lock:
            self._disabled = True


_GATE = _NetworkGate()


class _CustodiedStream(httpx.AsyncByteStream):
    def __init__(self, stream: httpx.AsyncByteStream) -> None:
        self._stream = stream

    def __aiter__(self) -> AsyncIterator[bytes]:
        return self._stream.__aiter__()

    async def aclose(self) -> None:
        try:
            await self._stream.aclose()
        except BaseException:
            _GATE.disable()
            raise


def _utc_epoch() -> int:
    return int(time.time())


def _response_policy(response: httpx.Response) -> int | None:
    headers = response.headers
    if (
        len(headers.raw) > _MAX_HEADERS
        or sum(len(name) + len(value) for name, value in headers.raw) > _MAX_HEADER_BYTES
        or response.status_code not in {200, 400, 401}
        or "set-cookie" in headers
        or "content-range" in headers
    ):
        raise AuthenticationUnavailable() from None
    for name in (
        "content-type",
        "content-length",
        "content-encoding",
        "transfer-encoding",
        "cache-control",
        "pragma",
        "age",
    ):
        if len(headers.get_list(name)) > 1:
            raise AuthenticationUnavailable() from None
    if (
        re.fullmatch(
            r'application/json(?:[ \t]*;[ \t]*charset=(?:utf-8|"utf-8"))?',
            headers.get("content-type", ""),
            re.IGNORECASE | re.ASCII,
        )
        is None
        or headers.get("content-encoding", "identity").lower() != "identity"
        or headers.get("age", "0") != "0"
    ):
        raise AuthenticationUnavailable() from None
    control = [item.strip().lower() for item in headers.get("cache-control", "").split(",")]
    if (
        len(control) != len(set(control))
        or "no-store" not in control
        or not set(control) <= {"no-store", "no-cache", "private", "must-revalidate", "max-age=0"}
        or headers.get("pragma", "").strip().lower() != "no-cache"
    ):
        raise AuthenticationUnavailable() from None
    transfer = headers.get("transfer-encoding")
    length_text = headers.get("content-length")
    if transfer is not None and (transfer.lower() != "chunked" or length_text is not None):
        raise AuthenticationUnavailable() from None
    if length_text is None:
        return None
    if re.fullmatch(r"[1-9][0-9]{0,4}", length_text, re.ASCII) is None:
        raise AuthenticationUnavailable() from None
    length = int(length_text)
    if length > MAX_RESPONSE_BYTES:
        raise AuthenticationUnavailable() from None
    return length


def _token_response(body: bytes, status: int) -> _TokenResponse:
    try:
        values = _object(body, MAX_RESPONSE_BYTES)
    except ValueError, TypeError, UnicodeError, RecursionError:
        raise AuthenticationUnavailable() from None
    if status != 200:
        if (
            status == 400
            and values.get("error") == "invalid_grant"
            and not {"id_token", "access_token", "refresh_token"} & values.keys()
        ):
            raise AuthenticationDenied() from None
        raise AuthenticationUnavailable() from None
    if (
        not {"id_token", "access_token", "token_type"} <= values.keys()
        or {"error", "refresh_token"} & values.keys()
        or type(values["token_type"]) is not str
        or values["token_type"].lower() != "bearer"
        or ("scope" in values and values["scope"] != "openid")
    ):
        raise AuthenticationUnavailable() from None
    for name in ("id_token", "access_token"):
        value = values[name]
        if (
            type(value) is not str
            or not 1 <= len(value) <= MAX_TOKEN_BYTES
            or re.fullmatch(r"[\x21-\x7e]+", value, re.ASCII) is None
        ):
            raise AuthenticationUnavailable() from None
    expires = values.get("expires_in")
    if "expires_in" in values and (type(expires) is not int or not 1 <= expires <= 3600):
        raise AuthenticationUnavailable() from None
    # Unknown, bounded extension fields are discarded, never used as authority.
    return _TokenResponse(SecretStr(values["id_token"]), SecretStr(values["access_token"]), expires)


class CodeExchanger:
    """One fixed confidential client; callers must durably consume attempts first.

    Test transports and clocks are trusted dependencies, never browser inputs.
    Each invocation can send at most once; this class is not a replay database.
    """

    def __init__(
        self,
        client: OidcClient,
        authentication: ClientSecretAuthentication,
        *,
        transport_factory: Callable[[], httpx.AsyncBaseTransport] | None = None,
        utc_clock: Callable[[], int] = _utc_epoch,
        monotonic_clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if (
            type(client) is not OidcClient
            or type(authentication) is not ClientSecretAuthentication
            or re.fullmatch(r"[A-Za-z0-9._~-]{1,100}", client.client_id, re.ASCII) is None
        ):
            raise AuthenticationUnavailable() from None
        self._client = client
        self._authentication = authentication
        self._transport_factory = transport_factory
        self._utc_clock = utc_clock
        self._monotonic_clock = monotonic_clock
        self._lock = threading.Lock()
        self._last_utc = 0
        self._last_monotonic = 0.0
        self._broken = False

    def _times(self) -> tuple[int, float]:
        try:
            utc, monotonic = self._utc_clock(), self._monotonic_clock()
            if (
                type(utc) is not int
                or not 0 <= utc <= MAX_TIMESTAMP
                or type(monotonic) not in (int, float)
                or not math.isfinite(monotonic)
                or not 0 <= monotonic <= 1e12
            ):
                raise ValueError()
            with self._lock:
                if self._broken or utc < self._last_utc or monotonic < self._last_monotonic:
                    raise ValueError()
                self._last_utc, self._last_monotonic = utc, float(monotonic)
            return utc, float(monotonic)
        except Exception:
            with self._lock:
                self._broken = True
            raise AuthenticationUnavailable() from None

    def _new_client(self) -> httpx.AsyncClient:
        transport = self._transport_factory() if self._transport_factory is not None else None
        return httpx.AsyncClient(
            transport=transport,
            verify=True,
            trust_env=False,
            follow_redirects=False,
            http1=True,
            http2=False,
            auth=None,
            proxy=None,
            timeout=httpx.Timeout(_IO_SECONDS, pool=1),
            limits=httpx.Limits(max_connections=1, max_keepalive_connections=0),
            headers={
                "Accept": "application/json",
                "Accept-Encoding": "identity",
                "Cache-Control": "no-cache",
                "User-Agent": "trading-app-code-exchanger/1",
            },
        )

    def _request(
        self, client: httpx.AsyncClient, attempt: LoginAttempt, code: SecretStr
    ) -> httpx.Request:
        body = _prepare_token_request(
            "authorization_code",
            redirect_uri=self._client.redirect_uri,
            code=code.get_secret_value(),
            code_verifier=attempt.pkce_verifier.get_secret_value(),
        )
        if type(body) is not str or not body.isascii() or not 1 <= len(body) <= MAX_REQUEST_BYTES:
            raise AuthenticationUnavailable() from None
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        auth = _client_authentication(
            self._client.client_id,
            self._authentication.secret.get_secret_value(),
            self._authentication.method,
        )
        uri, signed_headers, signed_body = auth.prepare(
            "POST", self._client.token_endpoint, headers, body
        )
        if (
            uri != self._client.token_endpoint
            or signed_body != body
            or set(signed_headers) != {"Content-Type", "Authorization"}
            or signed_headers["Content-Type"] != "application/x-www-form-urlencoded"
            or not signed_headers["Authorization"].startswith("Basic ")
            or len(signed_headers["Authorization"]) > 512
        ):
            raise AuthenticationUnavailable() from None
        return client.build_request(
            "POST", uri, headers=signed_headers, content=signed_body.encode("ascii")
        )

    async def _send(self, attempt: LoginAttempt, code: SecretStr, seconds: float) -> _TokenResponse:
        client = self._new_client()
        response: httpx.Response | None = None
        chunks: AsyncGenerator[bytes] | None = None
        raw = bytearray()
        try:
            async with asyncio.timeout(seconds):
                request = self._request(client, attempt, code)
                try:
                    response = await client.send(request, stream=True)
                except BaseException:
                    # HTTPcore may discard a closed connection before its hidden
                    # cleanup fails. Later client closure cannot prove custody ended.
                    _GATE.disable()
                    raise
                if not isinstance(response.stream, httpx.AsyncByteStream):
                    raise AuthenticationUnavailable() from None
                response.stream = _CustodiedStream(response.stream)
                length = _response_policy(response)
                chunks = response.aiter_raw(chunk_size=_CHUNK_BYTES)
                while True:
                    try:
                        chunk = await anext(chunks)
                    except StopAsyncIteration:
                        break
                    except BaseException:
                        _GATE.disable()
                        raise
                    if len(raw) + len(chunk) > MAX_RESPONSE_BYTES:
                        raise AuthenticationUnavailable() from None
                    raw.extend(chunk)
                if length is not None and len(raw) != length:
                    raise AuthenticationUnavailable() from None
                return _token_response(bytes(raw), response.status_code)
        finally:
            raw.clear()
            try:
                async with asyncio.timeout(_CLEANUP_SECONDS):
                    if chunks is not None:
                        await chunks.aclose()
                    if response is not None:
                        await response.aclose()
                    await client.aclose()
            except BaseException:
                _GATE.disable()
                raise
            finally:
                client.cookies.clear()

    async def exchange(
        self,
        attempt: LoginAttempt,
        callback: ParsedCallback,
        browser_binding: SecretStr,
    ) -> UnverifiedTokenResponse:
        if type(attempt) is not LoginAttempt or attempt.client != self._client:
            raise AuthenticationDenied() from None
        utc, _ = self._times()
        check_callback_binding(attempt, callback, browser_binding, utc)
        if callback.code is None:
            raise AuthenticationDenied() from None
        _GATE.acquire()
        try:
            utc, admitted = self._times()
            check_callback_binding(attempt, callback, browser_binding, utc)
            remaining = attempt.expires_at - utc
            result = await self._send(
                attempt, callback.code, float(min(REQUEST_SECONDS, remaining))
            )
            utc, completed = self._times()
            attempt.require_live(utc)
            if completed - admitted >= remaining:
                raise AuthenticationDenied() from None
            if completed - admitted >= REQUEST_SECONDS + _CLEANUP_SECONDS:
                raise AuthenticationUnavailable() from None
            return result
        except asyncio.CancelledError:
            raise
        except Exception as error:
            task = asyncio.current_task()
            if task is not None and task.cancelling():
                raise asyncio.CancelledError() from None
            if isinstance(error, AuthenticationDenied):
                raise AuthenticationDenied() from None
            raise AuthenticationUnavailable() from None
        finally:
            _GATE.release()
