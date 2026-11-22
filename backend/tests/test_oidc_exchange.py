import asyncio
import base64
import json
import logging
import ssl
from dataclasses import FrozenInstanceError, replace
from types import SimpleNamespace
from urllib.parse import parse_qs

import httpcore2
import httpx2 as httpx
import pytest
from authlib.oidc.core.util import create_half_hash
from cryptography.hazmat.primitives.asymmetric import rsa
from httpcore2._backends.base import AsyncNetworkBackend, AsyncNetworkStream
from joserfc import jwt
from joserfc.jwk import RSAKey
from pydantic import SecretStr

from trading_api.logging import SafeFormatter
from trading_auth.models import AuthenticationDenied, AuthenticationUnavailable
from trading_oidc import exchange as module
from trading_oidc import jwks as jwks_module
from trading_oidc.authorization import create_attempt
from trading_oidc.callback import ParsedCallback
from trading_oidc.contracts import OidcClient
from trading_oidc.exchange import ClientSecretAuthentication, CodeExchanger
from trading_oidc.verification import verify_id_token

NOW = 1_800_000_100
HEADERS = [
    ("Content-Type", "application/json"),
    ("Cache-Control", "no-store"),
    ("Pragma", "no-cache"),
]


class Clock:
    def __init__(self, value):
        self.value = value

    def __call__(self):
        return self.value


class Chunks(httpx.AsyncByteStream):
    def __init__(self, body, size=17):
        self.body = body
        self.size = size
        self.closed = False

    async def __aiter__(self):
        for offset in range(0, len(self.body), self.size):
            yield self.body[offset : offset + self.size]

    async def aclose(self):
        self.closed = True


class Transport(httpx.MockTransport):
    def __init__(self, handler):
        super().__init__(handler)
        self.closed = False

    async def aclose(self):
        self.closed = True
        await super().aclose()


class Source:
    def __init__(self, body, *, status=200, headers=None):
        self.body = body
        self.status = status
        self.headers = HEADERS if headers is None else headers
        self.requests = []
        self.streams = []
        self.transports = []
        self.failure = None
        self.stream_factory = Chunks
        self.transport_factory = Transport

    async def respond(self, request):
        self.requests.append(request)
        if self.failure:
            raise self.failure
        stream = self.stream_factory(self.body)
        self.streams.append(stream)
        return httpx.Response(self.status, headers=self.headers, stream=stream)

    def factory(self):
        transport = self.transport_factory(self.respond)
        self.transports.append(transport)
        return transport


@pytest.fixture(autouse=True)
def isolated_gate(monkeypatch):
    monkeypatch.setattr(module, "_GATE", module._NetworkGate())


@pytest.fixture(autouse=True)
def forbid_real_network(monkeypatch):
    original = httpx.AsyncHTTPTransport.handle_async_request
    attempted = []

    async def guarded(self, request):
        if isinstance(self._pool._network_backend, NoSocketBackend):
            return await original(self, request)
        attempted.append(True)
        raise AssertionError("Socket-capable transport reached by synthetic test.")

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", guarded)
    yield
    assert not attempted


@pytest.fixture
def context():
    client = OidcClient(
        "https://identity.example.test",
        "trading-personal",
        "https://identity.example.test/api/oidc/authorization",
        "https://identity.example.test/api/oidc/token",
        "https://identity.example.test/jwks.json",
        "https://trading.example.test/api/v1/auth/oidc/callback",
    )
    attempt = create_attempt(client, NOW - 100)
    callback = ParsedCallback(attempt.state, client.issuer, SecretStr("CODE+/%&=synthetic"))
    return SimpleNamespace(
        client=client,
        attempt=attempt,
        callback=callback,
        binding=attempt.browser_binding,
        auth=ClientSecretAuthentication(SecretStr("S" * 43)),
        utc=Clock(NOW),
        monotonic=Clock(100.0),
    )


@pytest.fixture
def values():
    return {
        "id_token": "synthetic.unverified.token",
        "access_token": "opaque-access",
        "token_type": "Bearer",
    }


def encoded(values):
    return json.dumps(values, separators=(",", ":")).encode()


def exchanger(context, source, **changes):
    return CodeExchanger(
        context.client,
        context.auth,
        transport_factory=source.factory,
        utc_clock=context.utc,
        monotonic_clock=context.monotonic,
        **changes,
    )


def run(context, source, *, engine=None):
    engine = engine or exchanger(context, source)
    return asyncio.run(engine.exchange(context.attempt, context.callback, context.binding))


def test_single_post_exact_binding_and_unverified_secret_result(context, values):
    source = Source(
        encoded(values | {"scope": "openid", "expires_in": 60, "extra": {"unused": True}})
    )
    result = run(context, source)
    assert result.id_token.get_secret_value() == values["id_token"]
    assert result.access_token.get_secret_value() == values["access_token"]
    assert result.expires_in == 60
    assert not hasattr(result, "identity") and not hasattr(result, "refresh_token")
    with pytest.raises(FrozenInstanceError):
        result.expires_in = 100
    assert len(source.requests) == 1
    request = source.requests[0]
    assert request.method == "POST" and str(request.url) == context.client.token_endpoint
    assert parse_qs(request.content.decode(), strict_parsing=True) == {
        "grant_type": ["authorization_code"],
        "code": [context.callback.code.get_secret_value()],
        "redirect_uri": [context.client.redirect_uri],
        "code_verifier": [context.attempt.pkce_verifier.get_secret_value()],
    }
    basic = base64.b64decode(request.headers["authorization"].removeprefix("Basic ")).decode()
    assert basic == context.client.client_id + ":" + context.auth.secret.get_secret_value()
    assert request.headers["accept-encoding"] == "identity"
    assert request.headers["content-type"] == "application/x-www-form-urlencoded"
    assert not {"cookie", "proxy-authorization"} & set(request.headers)
    assert context.auth.secret.get_secret_value().encode() not in request.content
    assert all(stream.closed for stream in source.streams)
    assert all(transport.closed for transport in source.transports)
    for item in (result, context.auth, exchanger(context, source)):
        assert "synthetic" not in repr(item) and "SSSS" not in repr(item)


@pytest.mark.parametrize("size", [43, 128])
def test_supported_secret_lengths(size):
    ClientSecretAuthentication(SecretStr("a" * size))


@pytest.mark.parametrize(
    "secret",
    [
        "x" * 42,
        "x" * 129,
        "x" * 43 + ":",
        "x" * 43 + "+",
        "x" * 43 + "%",
        "x" * 43 + "=",
        "x" * 43 + " ",
        "x" * 43 + "\n",
        "x" * 43 + "é",
        "",
    ],
)
def test_unsupported_secret_encoding_is_rejected(secret):
    with pytest.raises(AuthenticationUnavailable):
        ClientSecretAuthentication(SecretStr(secret))


@pytest.mark.parametrize("method", ["none", "client_secret_post", "private_key_jwt", "", None])
def test_no_authentication_method_fallback(method):
    with pytest.raises(AuthenticationUnavailable):
        ClientSecretAuthentication(SecretStr("S" * 43), method)


@pytest.mark.parametrize(
    "client_id", ["x" * 101, "has:colon", "has+plus", "has%escape", "has/slash"]
)
def test_basic_client_id_narrow_profile(context, client_id):
    with pytest.raises(AuthenticationUnavailable):
        CodeExchanger(replace(context.client, client_id=client_id), context.auth)


@pytest.mark.parametrize("client_id", ["x", "x" * 100, "trading._~-client"])
def test_unreserved_basic_client_ids(context, client_id):
    CodeExchanger(replace(context.client, client_id=client_id), context.auth)


@pytest.mark.parametrize(
    "change", ["client", "issuer", "state", "browser", "expired", "future", "error", "wrong-type"]
)
def test_binding_denial_before_transport(context, values, change):
    source = Source(encoded(values))
    engine = exchanger(context, source)
    if change == "client":
        context.attempt = replace(
            context.attempt,
            client=replace(context.client, redirect_uri="https://trading.example.test/other"),
        )
    elif change == "issuer":
        context.callback = replace(context.callback, issuer=context.client.issuer + "/")
    elif change == "state":
        context.callback = replace(context.callback, state=SecretStr("A" * 43))
    elif change == "browser":
        context.binding = SecretStr("B" * 43)
    elif change == "expired":
        context.utc.value = context.attempt.expires_at
    elif change == "future":
        context.utc.value = context.attempt.admitted_at - 1
    elif change == "error":
        context.callback = replace(context.callback, code=None)
    else:
        context.attempt = object()
    with pytest.raises(AuthenticationDenied):
        run(context, source, engine=engine)
    assert not source.requests and not source.transports


@pytest.mark.parametrize("expires", [None, 1, 3600])
@pytest.mark.parametrize("token_type", ["Bearer", "bearer", "BEARER"])
def test_success_metadata_is_only_a_hint(context, values, expires, token_type):
    values["token_type"] = token_type
    if expires is not None:
        values["expires_in"] = expires
    result = run(context, Source(encoded(values)))
    assert result.expires_in == expires


@pytest.mark.parametrize(
    "name,value",
    [
        ("id_token", ""),
        ("id_token", "x" * 16385),
        ("id_token", "x\ny"),
        ("id_token", "é"),
        ("id_token", None),
        ("access_token", "x y"),
        ("access_token", "x" * 16385),
        ("access_token", 10),
        ("token_type", "MAC"),
        ("token_type", None),
        ("scope", "openid profile"),
        ("scope", ["openid"]),
        ("expires_in", None),
        ("expires_in", True),
        ("expires_in", 0),
        ("expires_in", -1),
        ("expires_in", 3601),
        ("expires_in", 1.0),
        ("expires_in", "100"),
        ("refresh_token", None),
        ("refresh_token", "private"),
        ("error", "invalid_grant"),
    ],
)
def test_invalid_or_unsupported_success_is_unavailable(context, values, name, value):
    source = Source(encoded(values | {name: value}))
    with pytest.raises(AuthenticationUnavailable):
        run(context, source)
    assert len(source.requests) == 1 and not module._GATE._disabled


@pytest.mark.parametrize("field", ["id_token", "access_token", "token_type"])
def test_missing_required_success_field(context, values, field):
    del values[field]
    with pytest.raises(AuthenticationUnavailable):
        run(context, Source(encoded(values)))


@pytest.mark.parametrize("token_size", [1, 16384])
def test_token_size_boundaries(context, values, token_size):
    values.update(id_token="i" * token_size, access_token="a" * token_size)
    assert len(run(context, Source(encoded(values))).id_token.get_secret_value()) == token_size


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"[]",
        b"null",
        b"{}",
        b"\xff",
        b'{"x":1,"x":2}',
        b'{"x":NaN}',
        b'{"x":1.2}',
        b'{"x":' + b"[" * 6 + b"0" + b"]" * 6 + b"}",
    ],
)
def test_malformed_json_fails_privately(context, body):
    with pytest.raises(AuthenticationUnavailable) as error:
        run(context, Source(body))
    assert str(error.value) == "Authentication is temporarily unavailable."


def test_unknown_extension_shape_is_bounded(context, values):
    for extra in [{f"x{i}": i for i in range(17)}, {"extra": [1] * 17}]:
        with pytest.raises(AuthenticationUnavailable):
            run(context, Source(encoded(values | extra)))


@pytest.mark.parametrize(
    "status,error,expected",
    [
        (400, "invalid_grant", AuthenticationDenied),
        (400, "invalid_client", AuthenticationUnavailable),
        (401, "invalid_grant", AuthenticationUnavailable),
        (401, "invalid_client", AuthenticationUnavailable),
        (400, "unauthorized_client", AuthenticationUnavailable),
        (400, "CANARY_unrecognized", AuthenticationUnavailable),
    ],
)
def test_error_response_is_terminal_and_generic(context, status, error, expected):
    source = Source(
        encoded(
            {
                "error": error,
                "error_description": "CANARY_PRIVATE",
                "error_uri": "https://untrusted.invalid",
            }
        ),
        status=status,
    )
    with pytest.raises(expected) as caught:
        run(context, source)
    assert "CANARY" not in str(caught.value)
    assert len(source.requests) == 1 and not module._GATE._disabled


@pytest.mark.parametrize("status", [201, 204, 206, 301, 302, 303, 307, 308, 429, 500, 503])
def test_no_redirect_or_status_retry(context, values, status):
    source = Source(
        encoded(values),
        status=status,
        headers=[*HEADERS, ("Location", "https://untrusted.invalid"), ("Retry-After", "1")],
    )
    with pytest.raises(AuthenticationUnavailable):
        run(context, source)
    assert len(source.requests) == 1


@pytest.mark.parametrize(
    "extra",
    [
        [("Content-Type", "application/json")],
        [("Content-Length", "0")],
        [("Content-Length", "0001")],
        [("Content-Length", "65537")],
        [("Content-Length", "-1")],
        [("Content-Length", "1"), ("Transfer-Encoding", "chunked")],
        [("Transfer-Encoding", "gzip")],
        [("Content-Encoding", "gzip")],
        [("Content-Range", "bytes 0-1/100")],
        [("Set-Cookie", "CANARY=private")],
        [("Cache-Control", "no-store")],
        [("Pragma", "no-cache")],
        [("Age", "1")],
        [("Age", "00")],
    ],
)
def test_ambiguous_or_unsafe_headers(context, values, extra):
    with pytest.raises(AuthenticationUnavailable):
        run(context, Source(encoded(values), headers=[*HEADERS, *extra]))


@pytest.mark.parametrize(
    "field,value",
    [
        ("Content-Type", "text/html"),
        ("Content-Type", "application/json;charset=latin1"),
        ("Cache-Control", "public"),
        ("Cache-Control", "no-store, max-age=1"),
        ("Cache-Control", "no-store, no-store"),
        ("Cache-Control", ""),
        ("Pragma", ""),
        ("Pragma", "public"),
    ],
)
def test_required_response_policy(context, values, field, value):
    headers = [(name, value if name == field else existing) for name, existing in HEADERS]
    with pytest.raises(AuthenticationUnavailable):
        run(context, Source(encoded(values), headers=headers))


@pytest.mark.parametrize(
    "media",
    [
        "application/json",
        "APPLICATION/JSON",
        "application/json; charset=utf-8",
        'application/json;charset="UTF-8"',
    ],
)
def test_supported_media_and_exact_content_length(context, values, media):
    body = encoded(values)
    headers = [(key, media if key == "Content-Type" else value) for key, value in HEADERS]
    headers.append(("Content-Length", str(len(body))))
    assert run(context, Source(body, headers=headers)).expires_in is None


@pytest.mark.parametrize("excess", [0, 1])
def test_body_header_count_and_header_byte_boundaries(context, values, excess):
    body = encoded(values)
    padded = body + b" " * (65536 - len(body) + excess)
    source = Source(padded)
    if excess:
        with pytest.raises(AuthenticationUnavailable):
            run(context, source)
    else:
        run(context, source)
    headers = [*HEADERS, *[(f"X-{i}", "a") for i in range(61 + excess)]]
    if excess:
        with pytest.raises(AuthenticationUnavailable):
            run(context, Source(body, headers=headers))
    else:
        run(context, Source(body, headers=headers))
    used = sum(len(k) + len(v) for k, v in HEADERS)
    headers = [*HEADERS, ("X-Pad", "x" * (16384 - used - 5 + excess))]
    if excess:
        with pytest.raises(AuthenticationUnavailable):
            run(context, Source(body, headers=headers))
    else:
        run(context, Source(body, headers=headers))


def test_content_length_must_match_actual_body(context, values):
    for delta in [-1, 1]:
        body = encoded(values)
        with pytest.raises(AuthenticationUnavailable):
            run(
                context,
                Source(body, headers=[*HEADERS, ("Content-Length", str(len(body) + delta))]),
            )


def test_largest_callback_code_is_form_encoded_within_bound(context, values):
    context.callback = replace(context.callback, code=SecretStr("%" * 2048))
    source = Source(encoded(values))
    run(context, source)
    assert len(source.requests[0].content) <= 8192
    assert parse_qs(source.requests[0].content.decode())["code"] == ["%" * 2048]


@pytest.mark.parametrize(
    "which,bad",
    [
        ("utc", True),
        ("utc", -1),
        ("utc", NOW + 0.5),
        ("utc", 253402300800),
        ("monotonic", True),
        ("monotonic", float("nan")),
        ("monotonic", float("inf")),
        ("monotonic", -1),
        ("monotonic", 1e12 + 1),
    ],
)
def test_invalid_clocks_prevent_network(context, values, which, bad):
    getattr(context, which).value = bad
    source = Source(encoded(values))
    with pytest.raises(AuthenticationUnavailable):
        run(context, source)
    assert not source.requests


@pytest.mark.parametrize("which", ["utc", "monotonic"])
def test_clock_regression_latches_exchanger(context, values, which):
    source = Source(encoded(values))
    engine = exchanger(context, source)
    run(context, source, engine=engine)
    clock = getattr(context, which)
    clock.value -= 1
    with pytest.raises(AuthenticationUnavailable):
        run(context, source, engine=engine)
    clock.value += 2
    with pytest.raises(AuthenticationUnavailable):
        run(context, source, engine=engine)
    assert len(source.requests) == 1


@pytest.mark.parametrize("clock", ["utc", "monotonic"])
def test_late_success_after_attempt_expiry_is_discarded(context, values, clock):
    source = Source(encoded(values))

    class LateClose(Transport):
        async def aclose(self):
            if clock == "utc":
                context.utc.value = context.attempt.expires_at
            else:
                context.monotonic.value += 300
            await super().aclose()

    source.transport_factory = LateClose
    with pytest.raises(AuthenticationDenied):
        run(context, source)
    assert all(transport.closed for transport in source.transports)


def test_pinned_client_and_production_transport_settings(context, values, monkeypatch):
    source = Source(encoded(values))
    original = httpx.AsyncClient
    options = []

    def capture(**kwargs):
        options.append(kwargs)
        return original(**kwargs)

    monkeypatch.setattr(module.httpx, "AsyncClient", capture)
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "SSL_CERT_FILE", "SSL_CERT_DIR"):
        monkeypatch.setenv(name, "CANARY_UNTRUSTED_ENV")
    run(context, source)
    config = options[0]
    assert config["verify"] is True and config["trust_env"] is False
    assert config["follow_redirects"] is False
    assert config["auth"] is None and config["proxy"] is None
    assert config["http1"] is True and config["http2"] is False
    assert config["limits"].max_connections == 1
    assert config["limits"].max_keepalive_connections == 0
    assert config["timeout"].as_dict() == {"connect": 3, "read": 3, "write": 3, "pool": 1}
    engine = CodeExchanger(context.client, context.auth)

    async def inspect():
        client = engine._new_client()
        try:
            pool = client._transport._pool
            assert pool._retries == 0
            assert pool._max_connections == 1 and pool._max_keepalive_connections == 0
            assert pool._ssl_context.verify_mode == ssl.CERT_REQUIRED
            assert pool._ssl_context.check_hostname
            assert not client._mounts
        finally:
            await client.aclose()

    asyncio.run(inspect())


def test_cookies_are_rejected_cleared_and_not_reused(context, values, monkeypatch):
    clients = []
    original = httpx.AsyncClient

    def capture(**kwargs):
        client = original(**kwargs)
        clients.append(client)
        return client

    monkeypatch.setattr(module.httpx, "AsyncClient", capture)
    source = Source(encoded(values), headers=[*HEADERS, ("Set-Cookie", "CANARY=private; Secure")])
    with pytest.raises(AuthenticationUnavailable):
        run(context, source)
    assert not clients[0].cookies
    source.headers = HEADERS
    run(context, source)
    assert "cookie" not in source.requests[1].headers


def test_transport_exception_is_private_and_latches_replacements(context, values):
    source = Source(encoded(values))
    source.failure = httpx.ReadError("CANARY_PRIVATE")
    with pytest.raises(AuthenticationUnavailable) as caught:
        run(context, source)
    assert "CANARY" not in str(caught.value)
    assert module._GATE._disabled
    with pytest.raises(AuthenticationUnavailable):
        run(context, source)
    assert len(source.requests) == 1
    record = logging.LogRecord("httpx", logging.ERROR, "", 1, "CANARY_PRIVATE", (), None)
    assert "CANARY_PRIVATE" not in SafeFormatter().format(record)


@pytest.mark.parametrize("where", ["stream", "client"])
def test_explicit_close_failure_never_returns_tokens(context, values, where):
    source = Source(encoded(values))

    class BrokenStream(Chunks):
        async def aclose(self):
            raise RuntimeError("CANARY_STREAM_CLOSE")

    class BrokenClient(Transport):
        async def aclose(self):
            raise RuntimeError("CANARY_CLIENT_CLOSE")

    if where == "stream":
        source.stream_factory = BrokenStream
    else:
        source.transport_factory = BrokenClient
    with pytest.raises(AuthenticationUnavailable) as caught:
        run(context, source)
    assert "CANARY" not in str(caught.value)
    assert module._GATE._disabled and not module._GATE._busy
    with pytest.raises(AuthenticationUnavailable):
        run(context, source)
    assert len(source.requests) == 1


def test_nonqueued_custody_extends_through_cleanup(context, values):
    async def scenario():
        closing, release = asyncio.Event(), asyncio.Event()
        source = Source(encoded(values))

        class SlowClose(Transport):
            async def aclose(self):
                closing.set()
                await release.wait()
                await super().aclose()

        source.transport_factory = SlowClose
        task = asyncio.create_task(
            exchanger(context, source).exchange(context.attempt, context.callback, context.binding)
        )
        await closing.wait()
        with pytest.raises(AuthenticationUnavailable):
            await exchanger(context, source).exchange(
                context.attempt, context.callback, context.binding
            )
        assert len(source.requests) == 1 and module._GATE._busy
        release.set()
        await task
        assert not module._GATE._busy
        assert len(asyncio.all_tasks()) == 1

    asyncio.run(scenario())


def test_cancellation_during_cleanup_latches_without_detached_tasks(context, values):
    async def scenario():
        closing = asyncio.Event()
        source = Source(encoded(values))

        class SlowClose(Transport):
            async def aclose(self):
                closing.set()
                await asyncio.Event().wait()

        source.transport_factory = SlowClose
        task = asyncio.create_task(
            exchanger(context, source).exchange(context.attempt, context.callback, context.binding)
        )
        await closing.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert module._GATE._disabled and not module._GATE._busy
        assert len(asyncio.all_tasks()) == 1

    asyncio.run(scenario())


def test_cleanup_deadline_latches(context, values, monkeypatch):
    monkeypatch.setattr(module, "_CLEANUP_SECONDS", 0.01)
    source = Source(encoded(values))

    class SlowClose(Transport):
        async def aclose(self):
            await asyncio.Event().wait()

    source.transport_factory = SlowClose
    with pytest.raises(AuthenticationUnavailable):
        run(context, source)
    assert module._GATE._disabled and not module._GATE._busy


def test_exchange_does_not_claim_durable_replay_or_share_jwks_gate(context, values):
    source = Source(encoded(values))
    assert module._GATE is not jwks_module._GATE
    engine = exchanger(context, source)
    run(context, source, engine=engine)
    run(context, source, engine=engine)
    assert len(source.requests) == 2  # Caller must provide durable single-use authority.


class NoSocketStream(AsyncNetworkStream):
    def __init__(self, backend):
        self.backend = backend
        self.wire = bytearray(backend.wire)
        self.closed = False
        self.close_calls = 0

    async def write(self, buffer, **kwargs):
        self.backend.requests.append(buffer)

    async def start_tls(self, **kwargs):
        return self

    async def read(self, max_bytes, **kwargs):
        if self.wire:
            chunk = bytes(self.wire[:max_bytes])
            del self.wire[:max_bytes]
            return chunk
        self.backend.entered.set()
        if self.backend.block:
            await asyncio.Event().wait()
        if self.backend.read_error:
            raise httpcore2.ReadError("CANARY_WIRE_READ")
        return b""

    async def aclose(self):
        self.close_calls += 1
        if self.backend.close_error:
            raise RuntimeError("CANARY_HIDDEN_WIRE_CLOSE")
        self.closed = True


class NoSocketBackend(AsyncNetworkBackend):
    def __init__(self, wire=b"", *, read_error=False, close_error=False, block=False):
        self.wire = wire
        self.read_error = read_error
        self.close_error = close_error
        self.block = block
        self.entered = asyncio.Event()
        self.streams = []
        self.requests = []

    async def connect_tcp(self, **kwargs):
        assert kwargs["host"] == "identity.example.test" and kwargs["port"] == 443
        stream = NoSocketStream(self)
        self.streams.append(stream)
        return stream

    async def connect_unix_socket(self, **kwargs):
        raise AssertionError("Unix socket requested by synthetic test.")

    async def sleep(self, seconds):
        raise AssertionError("Retry requested by synthetic test.")

    def factory(self):
        transport = httpx.AsyncHTTPTransport(
            verify=True,
            trust_env=False,
            retries=0,
            http2=False,
            limits=httpx.Limits(max_connections=1, max_keepalive_connections=0),
        )
        transport._pool._network_backend = self
        return transport


def wire_headers(length):
    return (
        b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
        b"Cache-Control: no-store\r\nPragma: no-cache\r\n"
        + f"Content-Length: {length}\r\n\r\n".encode()
    )


@pytest.mark.parametrize("phase", ["headers", "body"])
@pytest.mark.parametrize("close_error", [False, True])
@pytest.mark.parametrize("failure", ["read", "cancel", "timeout"])
def test_real_transport_uncertainty_latches_even_after_hidden_close_failure(
    context, phase, close_error, failure, monkeypatch
):
    async def scenario():
        wire = b"" if phase == "headers" else wire_headers(1000)
        backend = NoSocketBackend(
            wire, read_error=failure == "read", close_error=close_error, block=failure != "read"
        )
        engine = exchanger(context, backend)
        operation = engine.exchange(context.attempt, context.callback, context.binding)
        if failure == "cancel":
            task = asyncio.create_task(operation)
            await backend.entered.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert task.cancelled()
        else:
            with pytest.raises(AuthenticationUnavailable) as caught:
                await operation
            assert "CANARY" not in str(caught.value)
        assert module._GATE._disabled and not module._GATE._busy
        assert len(backend.streams) == 1
        assert backend.streams[0].close_calls == 1
        with pytest.raises(AuthenticationUnavailable):
            await exchanger(context, backend).exchange(
                context.attempt, context.callback, context.binding
            )
        assert len(backend.streams) == 1
        assert len(asyncio.all_tasks()) == 1

    if failure == "timeout":
        monkeypatch.setattr(module, "REQUEST_SECONDS", 0.01)
    asyncio.run(scenario())


@pytest.mark.parametrize("form", ["twice", "comma", "many", "conflict"])
def test_real_parser_content_length_normalization_and_conflict(context, values, form):
    body = encoded(values)
    length = str(len(body)).encode()
    fields = b"Content-Length: " + length + b"\r\n"
    if form == "comma":
        fields = b"Content-Length: " + length + b", " + length + b"\r\n"
    elif form == "conflict":
        fields += b"Content-Length: 1\r\n"
    else:
        fields *= 1000 if form == "many" else 2
    prefix = (
        b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
        b"Cache-Control: no-store\r\nPragma: no-cache\r\n"
    )
    backend = NoSocketBackend(prefix + fields + b"\r\n" + body)
    if form == "conflict":
        with pytest.raises(AuthenticationUnavailable):
            run(context, backend)
        assert module._GATE._disabled
    else:
        assert run(context, backend).access_token.get_secret_value() == values["access_token"]
        assert not module._GATE._disabled
    assert backend.streams[0].closed


def test_real_parser_keeps_duplicate_critical_fields_for_rejection(context, values):
    body = encoded(values)
    wire = (
        wire_headers(len(body)).replace(
            b"Pragma: no-cache\r\n", b"Pragma: no-cache\r\nPragma: no-cache\r\n"
        )
        + body
    )
    with pytest.raises(AuthenticationUnavailable):
        run(context, NoSocketBackend(wire))
    assert not module._GATE._disabled


@pytest.fixture(scope="module")
def private_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.mark.parametrize(
    "change",
    [
        {},
        {"nonce": "N" * 43},
        {"amr": ["pwd"]},
        {"aud": "other"},
        {"at_hash": "A" * 22},
        {"exp": NOW},
    ],
)
def test_exchange_composes_with_explicit_offline_verification_only(context, private_key, change):
    access = "synthetic-opaque-access"
    claims = {
        "iss": context.client.issuer,
        "sub": "Opaque_Subject",
        "aud": context.client.client_id,
        "iat": NOW - 10,
        "exp": NOW + 600,
        "auth_time": NOW - 20,
        "nonce": context.attempt.nonce.get_secret_value(),
        "amr": ["pwd", "otp", "mfa"],
        "at_hash": create_half_hash(access, "RS256").decode(),
    } | change
    signing_key = RSAKey.import_key(private_key)
    token = jwt.encode({"alg": "RS256", "kid": "key-1"}, claims, signing_key)
    result = run(
        context,
        Source(encoded({"id_token": token, "access_token": access, "token_type": "Bearer"})),
    )
    assert not hasattr(result, "identity")
    keys = encoded(
        {
            "keys": [
                RSAKey.import_key(private_key.public_key()).as_dict()
                | {"kid": "key-1", "alg": "RS256"}
            ]
        }
    )
    if change:
        with pytest.raises(AuthenticationDenied):
            verify_id_token(
                result.id_token, keys, context.attempt, NOW, access_token=result.access_token
            )
    else:
        evidence = verify_id_token(
            result.id_token, keys, context.attempt, NOW, access_token=result.access_token
        )
        assert evidence.identity.subject == "Opaque_Subject"
        assert not hasattr(evidence, "id_token") and not hasattr(evidence, "owner")


def test_cancellation_before_start_sends_nothing(context, values):
    async def scenario():
        source = Source(encoded(values))
        task = asyncio.create_task(
            exchanger(context, source).exchange(context.attempt, context.callback, context.binding)
        )
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not source.requests and not source.transports
        assert not module._GATE._disabled and not module._GATE._busy

    asyncio.run(scenario())


def test_original_attempt_deadline_caps_request_budget(context, values, monkeypatch):
    context.utc.value = context.attempt.expires_at - 1
    original = asyncio.timeout
    budgets = []

    def capture(seconds):
        budgets.append(seconds)
        return original(seconds)

    monkeypatch.setattr(module.asyncio, "timeout", capture)
    run(context, Source(encoded(values)))
    assert budgets == [1.0, 3]


@pytest.mark.parametrize("body", ["x" * 8193, b"not-text", "non-ascii-é", ""])
def test_request_preparation_limits_fail_before_send(context, values, monkeypatch, body):
    monkeypatch.setattr(module, "_prepare_token_request", lambda *args, **kwargs: body)
    source = Source(encoded(values))
    with pytest.raises(AuthenticationUnavailable):
        run(context, source)
    assert not source.requests
    assert all(transport.closed for transport in source.transports)


@pytest.mark.parametrize("change", ["uri", "body", "header", "method"])
def test_auth_preparation_cannot_change_destination_or_add_credentials(
    context, values, monkeypatch, change
):
    class AlteredAuthentication:
        def prepare(self, method, uri, headers, body):
            headers = dict(headers) | {"Authorization": "Basic synthetic"}
            if change == "uri":
                uri = "https://untrusted.invalid/token"
            elif change == "body":
                body += "&client_secret=synthetic"
            elif change == "header":
                headers["Cookie"] = "synthetic"
            else:
                headers["Authorization"] = "Bearer synthetic"
            return uri, headers, body

    monkeypatch.setattr(module, "_client_authentication", lambda *args: AlteredAuthentication())
    source = Source(encoded(values))
    with pytest.raises(AuthenticationUnavailable):
        run(context, source)
    assert not source.requests


def test_second_cancellation_during_active_fetch_cleanup(context, values):
    async def scenario():
        body_entered, closing = asyncio.Event(), asyncio.Event()
        source = Source(encoded(values))

        class BlockedBody(Chunks):
            async def __aiter__(self):
                body_entered.set()
                await asyncio.Event().wait()
                yield b"unreachable"

            async def aclose(self):
                closing.set()
                await asyncio.Event().wait()

        source.stream_factory = BlockedBody
        task = asyncio.create_task(
            exchanger(context, source).exchange(context.attempt, context.callback, context.binding)
        )
        await body_entered.wait()
        task.cancel()
        await closing.wait()
        assert module._GATE._busy
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert module._GATE._disabled and not module._GATE._busy
        assert len(asyncio.all_tasks()) == 1

    asyncio.run(scenario())
