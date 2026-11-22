"""Fixed-issuer public-key acquisition; no application routes or token exchange."""

import asyncio
import math
import re
import threading
import time
from collections.abc import AsyncGenerator, AsyncIterator, Callable
from dataclasses import dataclass

import httpx2 as httpx

from trading_auth.models import AuthenticationUnavailable
from trading_oidc.contracts import OidcClient
from trading_oidc.verification import MAX_JWKS_BYTES, _keys

READ_SECONDS = 10
CACHE_SECONDS = 60
FAILURE_SECONDS = 30
_CLEANUP_SECONDS = 3
_IO_SECONDS = 3
_CHUNK_BYTES = 4096
_MAX_HEADERS = 64
_MAX_HEADER_BYTES = 16384


@dataclass(frozen=True, repr=False)
class _Snapshot:
    body: bytes
    expires_at: float


class _NetworkGate:
    """Nonqueued process-wide custody; uncertain cleanup disables further reads."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._busy = False
        self._disabled = False

    def acquire(self) -> None:
        with self._lock:
            if self._busy or self._disabled:
                raise AuthenticationUnavailable() from None
            self._busy = True

    def disable(self) -> None:
        with self._lock:
            self._disabled = True

    def release(self) -> None:
        with self._lock:
            self._busy = False


_GATE = _NetworkGate()


class _CustodiedStream(httpx.AsyncByteStream):
    """Observe close failure before HTTPX's idempotent response flag hides it."""

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


def _decimal(value: str) -> int:
    if re.fullmatch(r"0|[1-9][0-9]{0,8}", value, re.ASCII) is None:
        raise AuthenticationUnavailable() from None
    return int(value)


def _response_policy(response: httpx.Response) -> tuple[int | None, float, bool]:
    # These are parsed fields. h11 may normalize equivalent Content-Length
    # duplicates before this layer; conflicting framing is rejected by h11.
    headers = response.headers
    if (
        len(headers.raw) > _MAX_HEADERS
        or sum(len(name) + len(value) for name, value in headers.raw) > _MAX_HEADER_BYTES
        or response.status_code != 200
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
        "age",
    ):
        if len(headers.get_list(name)) > 1:
            raise AuthenticationUnavailable() from None
    media = headers.get("content-type", "")
    if (
        len(media) > 128
        or re.fullmatch(
            r'application/(?:json|jwk-set\+json)(?:[ \t]*;[ \t]*charset=(?:utf-8|"utf-8"))?',
            media,
            re.IGNORECASE | re.ASCII,
        )
        is None
        or headers.get("content-encoding", "identity").lower() != "identity"
    ):
        raise AuthenticationUnavailable() from None
    transfer = headers.get("transfer-encoding")
    length_value = headers.get("content-length")
    if transfer is not None and (transfer.lower() != "chunked" or length_value is not None):
        raise AuthenticationUnavailable() from None
    length = None if length_value is None else _decimal(length_value)
    if length is not None and not 1 <= length <= MAX_JWKS_BYTES:
        raise AuthenticationUnavailable() from None

    # Restricted application cache policy, not a general HTTP cache parser.
    maximum = CACHE_SECONDS
    cacheable = True
    control = headers.get("cache-control")
    if control is not None:
        seen: set[str] = set()
        for item in control.split(","):
            directive = item.strip().lower()
            name, separator, value = directive.partition("=")
            if name in seen:
                cacheable = False
            seen.add(name)
            if directive in {"public", "private", "must-revalidate"}:
                continue
            if name == "max-age" and separator:
                try:
                    age_limit = _decimal(value)
                except AuthenticationUnavailable:
                    cacheable = False
                else:
                    if age_limit == 0:
                        cacheable = False
                    else:
                        maximum = min(maximum, age_limit)
            else:
                cacheable = False
    age = _decimal(headers.get("age", "0"))
    if age >= maximum or (not cacheable and age > 0):
        raise AuthenticationUnavailable() from None
    return length, float(maximum - age), cacheable


class JwksReader:
    """One exact client configuration and one short-lived validated snapshot.

    The clock and transport factory are trusted test seams, never request inputs.
    Returned bytes are fresh at delivery; callers verify synchronously with the
    same client and must not retain them as a substitute for future reads.
    """

    def __init__(
        self,
        client: OidcClient,
        *,
        transport_factory: Callable[[], httpx.AsyncBaseTransport] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if type(client) is not OidcClient:
            raise AuthenticationUnavailable() from None
        self._client = client
        self._transport_factory = transport_factory
        self._clock = clock
        self._lock = threading.Lock()
        self._snapshot: _Snapshot | None = None
        self._last_time = 0.0
        self._retry_at = 0.0
        self._broken = False

    def _now(self) -> float:
        try:
            value = self._clock()
            if (
                type(value) not in (int, float)
                or not math.isfinite(value)
                or not 0 <= value <= 1e12
            ):
                raise ValueError()
            with self._lock:
                if self._broken or value < self._last_time:
                    raise ValueError()
                self._last_time = value
            return float(value)
        except Exception:
            with self._lock:
                self._broken = True
                self._snapshot = None
            raise AuthenticationUnavailable() from None

    def _failed(self) -> None:
        with self._lock:
            self._snapshot = None
        try:
            current = self._now()
        except AuthenticationUnavailable:
            return
        with self._lock:
            self._retry_at = current + FAILURE_SECONDS

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
                "Accept": "application/json, application/jwk-set+json",
                "Accept-Encoding": "identity",
                "Cache-Control": "no-cache",
                "User-Agent": "trading-app-jwks-reader/1",
            },
        )

    async def _fetch(self) -> tuple[bytes, float, bool]:
        client = self._new_client()
        response: httpx.Response | None = None
        chunks: AsyncGenerator[bytes] | None = None
        raw = bytearray()
        try:
            async with asyncio.timeout(READ_SECONDS):
                request = client.build_request("GET", self._client.jwks_uri)
                try:
                    response = await client.send(request, stream=True)
                except BaseException:
                    # Transport cleanup can fail internally after HTTPcore has
                    # already discarded a connection marked closed. A later
                    # successful client.close cannot establish ended custody.
                    _GATE.disable()
                    raise
                if not isinstance(response.stream, httpx.AsyncByteStream):
                    raise AuthenticationUnavailable() from None
                response.stream = _CustodiedStream(response.stream)
                length, lifetime, cacheable = _response_policy(response)
                chunks = response.aiter_raw(chunk_size=_CHUNK_BYTES)
                while True:
                    try:
                        chunk = await anext(chunks)
                    except StopAsyncIteration:
                        break
                    except BaseException:
                        # Includes timeout/cancellation and cleanup failures
                        # hidden inside the maintained HTTP transport.
                        _GATE.disable()
                        raise
                    if len(raw) + len(chunk) > MAX_JWKS_BYTES:
                        raise AuthenticationUnavailable() from None
                    raw.extend(chunk)
                if length is not None and len(raw) != length:
                    raise AuthenticationUnavailable() from None
                body = bytes(raw)
                _keys(body)
                return body, lifetime, cacheable
        finally:
            raw.clear()
            # Cleanup stays in this task. A second cancellation or failed close
            # disables new network admission instead of claiming custody ended.
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

    async def read(self, client: OidcClient) -> bytes:
        if type(client) is not OidcClient or client != self._client:
            raise AuthenticationUnavailable() from None
        current = self._now()
        with self._lock:
            snapshot = self._snapshot
            if snapshot is not None and current < snapshot.expires_at:
                return snapshot.body
            self._snapshot = None
            if current < self._retry_at:
                raise AuthenticationUnavailable() from None
        _GATE.acquire()
        try:
            admitted = self._now()
            body, lifetime, cacheable = await self._fetch()
            current = self._now()
            expires_at = admitted + lifetime
            if current >= expires_at:
                raise AuthenticationUnavailable() from None
            with self._lock:
                if cacheable:
                    self._snapshot = _Snapshot(body, expires_at)
            return body
        except asyncio.CancelledError:
            self._failed()
            raise
        except Exception:
            self._failed()
            task = asyncio.current_task()
            if task is not None and task.cancelling():
                # A lower-level cleanup error may have replaced CancelledError.
                raise asyncio.CancelledError() from None
            raise AuthenticationUnavailable() from None
        finally:
            _GATE.release()
