import asyncio
import json
import logging
from dataclasses import replace

import httpcore2
import httpx2 as httpx
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from httpcore2._backends.base import AsyncNetworkBackend, AsyncNetworkStream
from joserfc import jwt
from joserfc.jwk import RSAKey
from pydantic import SecretStr

from trading_api.logging import SafeFormatter
from trading_auth.models import AuthenticationDenied, AuthenticationUnavailable
from trading_oidc import jwks as module
from trading_oidc.authorization import create_attempt
from trading_oidc.contracts import OidcClient
from trading_oidc.jwks import JwksReader
from trading_oidc.verification import verify_id_token


class Clock:
    def __init__(self):
        self.value = 100.0

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
    def __init__(self, body, headers=None, status=200):
        self.body = body
        self.headers = [("content-type", "application/json")] if headers is None else headers
        self.status = status
        self.requests = []
        self.streams = []
        self.transports = []
        self.failure = None

    async def respond(self, request):
        self.requests.append(request)
        if self.failure is not None:
            raise self.failure
        stream = Chunks(self.body)
        self.streams.append(stream)
        return httpx.Response(self.status, headers=self.headers, stream=stream)

    def factory(self):
        transport = Transport(self.respond)
        self.transports.append(transport)
        return transport


@pytest.fixture(autouse=True)
def isolated_gate(monkeypatch):
    monkeypatch.setattr(module, "_GATE", module._NetworkGate())


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def client():
    return OidcClient(
        "https://identity.example.test",
        "trading-personal",
        "https://identity.example.test/api/oidc/authorization",
        "https://identity.example.test/api/oidc/token",
        "https://identity.example.test/jwks.json",
        "https://trading.example.test/api/v1/auth/oidc/callback",
    )


@pytest.fixture(scope="module")
def private():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def body(private):
    public = RSAKey.import_key(private.public_key()).as_dict()
    return json.dumps({"keys": [public | {"kid": "old", "alg": "RS256", "use": "sig"}]}).encode()


def reader_for(client, clock, source):
    return JwksReader(client, transport_factory=source.factory, clock=clock)


def run(reader, client):
    return asyncio.run(reader.read(client))


def test_fixed_destination_fresh_reuse_and_owned_transport(client, clock, body):
    source = Source(body)
    reader = reader_for(client, clock, source)
    assert run(reader, client) == body
    clock.value = 159.999
    assert run(reader, client) == body
    assert len(source.requests) == 1
    request = source.requests[0]
    assert request.method == "GET"
    assert str(request.url) == client.jwks_uri
    assert request.headers["accept"] == "application/json, application/jwk-set+json"
    assert request.headers["accept-encoding"] == "identity"
    assert request.headers["cache-control"] == "no-cache"
    assert not {"authorization", "cookie", "proxy-authorization"} & set(request.headers)
    assert request.content == b""
    assert all(stream.closed for stream in source.streams)
    assert all(transport.closed for transport in source.transports)
    assert client.issuer not in repr(reader)
    assert body.decode() not in repr(reader)


@pytest.mark.parametrize(
    "change",
    [
        {"client_id": "other"},
        {"jwks_uri": "https://identity.example.test/other.json"},
        {"redirect_uri": "https://trading.example.test/other"},
        {
            "issuer": "https://other.example.test",
            "authorization_endpoint": "https://other.example.test/auth",
            "token_endpoint": "https://other.example.test/token",
            "jwks_uri": "https://other.example.test/jwks",
        },
    ],
)
def test_no_cross_client_or_configuration_cache(client, clock, body, change):
    source = Source(body)
    reader = reader_for(client, clock, source)
    assert run(reader, client) == body
    with pytest.raises(AuthenticationUnavailable):
        run(reader, replace(client, **change))
    assert len(source.requests) == 1
    second = reader_for(client, clock, source)
    assert run(second, client) == body
    assert len(source.requests) == 2


def test_pinned_client_settings_ignore_environment(monkeypatch, client, clock, body):
    source = Source(body)
    original = httpx.AsyncClient
    options = []

    def capture(**kwargs):
        options.append(kwargs)
        return original(**kwargs)

    monkeypatch.setattr(module.httpx, "AsyncClient", capture)
    for variable in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "SSL_CERT_FILE", "SSL_CERT_DIR"):
        monkeypatch.setenv(variable, "canary-untrusted-environment")
    assert run(reader_for(client, clock, source), client) == body
    config = options[0]
    assert config["verify"] is True and config["trust_env"] is False
    assert config["follow_redirects"] is False and config["http2"] is False
    assert config["auth"] is None and config["proxy"] is None
    assert config["limits"].max_connections == 1
    assert config["limits"].max_keepalive_connections == 0
    assert config["timeout"].as_dict() == {"connect": 3, "read": 3, "write": 3, "pool": 1}


@pytest.mark.parametrize(
    "media",
    ["application/json", "application/jwk-set+json", 'Application/JSON; charset="UTF-8"'],
)
def test_supported_media_and_exact_length(client, clock, body, media):
    source = Source(body, [("content-type", media), ("content-length", str(len(body)))])
    assert run(reader_for(client, clock, source), client) == body


@pytest.mark.parametrize(
    "headers",
    [
        [("content-type", "application/json"), ("content-type", "application/json")],
        [("content-type", "application/json"), ("content-length", "1"), ("content-length", "1")],
        [("content-type", "text/html")],
        [("content-type", "application/json; charset=latin1")],
        [("content-type", "application/json"), ("content-encoding", "gzip")],
        [("content-type", "application/json"), ("content-encoding", "identity, identity")],
        [
            ("content-type", "application/json"),
            ("content-encoding", "identity"),
            ("content-encoding", "identity"),
        ],
        [("content-type", "application/json"), ("content-range", "bytes 0-5/100")],
        [("content-type", "application/json"), ("set-cookie", "canary=private; Secure")],
        [("content-type", "application/json"), ("transfer-encoding", "gzip")],
        [
            ("content-type", "application/json"),
            ("transfer-encoding", "chunked"),
            ("content-length", "100"),
        ],
        [
            ("content-type", "application/json"),
            ("transfer-encoding", "chunked"),
            ("transfer-encoding", "chunked"),
        ],
        [
            ("content-type", "application/json"),
            ("cache-control", "max-age=60"),
            ("cache-control", "max-age=60"),
        ],
        [("content-type", "application/json"), ("age", "0"), ("age", "0")],
        [],
    ],
)
def test_ambiguous_or_unsupported_headers_fail_closed(client, clock, body, headers):
    source = Source(body, headers)
    with pytest.raises(AuthenticationUnavailable):
        run(reader_for(client, clock, source), client)
    assert len(source.requests) == 1
    assert all(transport.closed for transport in source.transports)


@pytest.mark.parametrize("length", ["0", "-1", "01", "1.0", "+7", "65537", "9999999999", "1"])
def test_invalid_or_mismatched_lengths(client, clock, body, length):
    source = Source(body, [("content-type", "application/json"), ("content-length", length)])
    with pytest.raises(AuthenticationUnavailable):
        run(reader_for(client, clock, source), client)


@pytest.mark.parametrize("status", [201, 204, 206, 301, 302, 307, 308, 304, 401, 429, 500, 503])
def test_no_redirect_or_failure_retries(client, clock, body, status):
    source = Source(body, [("location", "https://canary-untrusted.test/keys")], status)
    reader = reader_for(client, clock, source)
    for _ in range(2):
        with pytest.raises(AuthenticationUnavailable):
            run(reader, client)
    assert len(source.requests) == 1


@pytest.mark.parametrize("extra,accepted", [(0, True), (1, False)])
def test_body_limit(client, clock, body, extra, accepted):
    padded = body + b" " * (65536 - len(body) + extra)
    source = Source(padded)
    reader = reader_for(client, clock, source)
    if accepted:
        assert run(reader, client) == padded
    else:
        with pytest.raises(AuthenticationUnavailable):
            run(reader, client)


@pytest.mark.parametrize("count,accepted", [(63, True), (64, False)])
def test_header_count_bound(client, clock, body, count, accepted):
    source = Source(body, [("content-type", "application/json")] + [("x", "y")] * count)
    if accepted:
        assert run(reader_for(client, clock, source), client) == body
    else:
        with pytest.raises(AuthenticationUnavailable):
            run(reader_for(client, clock, source), client)


@pytest.mark.parametrize("extra,accepted", [(0, True), (1, False)])
def test_header_byte_bound(client, clock, body, extra, accepted):
    headers = [(b"content-type", b"application/json")]
    used = sum(len(name) + len(value) for name, value in headers) + len(b"x-fill")
    headers.append((b"x-fill", b"x" * (16384 - used + extra)))
    source = Source(body, headers)
    if accepted:
        assert run(reader_for(client, clock, source), client) == body
    else:
        with pytest.raises(AuthenticationUnavailable):
            run(reader_for(client, clock, source), client)


@pytest.mark.parametrize(
    "update",
    [
        {"alg": "RS384"},
        {"kty": "oct"},
        {"d": "private"},
        {"x5c": ["certificate"]},
        {"key_ops": ["sign"]},
        {"use": "enc"},
        {"e": "Aw"},
        {"kid": ""},
    ],
)
def test_same_strict_key_profile_as_offline_verifier(client, clock, body, update):
    keys = json.loads(body)
    keys["keys"][0].update(update)
    source = Source(json.dumps(keys).encode())
    with pytest.raises(AuthenticationUnavailable):
        run(reader_for(client, clock, source), client)


@pytest.mark.parametrize(
    "invalid",
    [b"", b"not-json", b'{"keys":[]}', b'{"keys":[],"keys":[]}', b'{"keys":[null]}'],
)
def test_malformed_jwks_never_cached(client, clock, invalid):
    source = Source(invalid)
    reader = reader_for(client, clock, source)
    for _ in range(2):
        with pytest.raises(AuthenticationUnavailable):
            run(reader, client)
    assert len(source.requests) == 1


def test_mixed_keys_and_duplicate_kids_are_not_projected(client, clock, body):
    keys = json.loads(body)
    keys["keys"].append(keys["keys"][0] | {"kid": "other", "alg": "ES256"})
    source = Source(json.dumps(keys).encode())
    with pytest.raises(AuthenticationUnavailable):
        run(reader_for(client, clock, source), client)
    source.body = json.dumps({"keys": [json.loads(body)["keys"][0]] * 2}).encode()
    with pytest.raises(AuthenticationUnavailable):
        run(reader_for(client, clock, source), client)


@pytest.mark.parametrize("count,accepted", [(8, True), (9, False)])
def test_key_count_bound(client, clock, body, count, accepted):
    key = json.loads(body)["keys"][0]
    source = Source(json.dumps({"keys": [key | {"kid": f"k{n}"} for n in range(count)]}).encode())
    if accepted:
        assert run(reader_for(client, clock, source), client) == source.body
    else:
        with pytest.raises(AuthenticationUnavailable):
            run(reader_for(client, clock, source), client)


@pytest.mark.parametrize(
    "control,expires",
    [
        (None, 60),
        ("public, max-age=600", 60),
        ("max-age=2", 2),
        ("private, max-age=15, must-revalidate", 15),
    ],
)
def test_cache_lifetime_only_shortens(client, clock, body, control, expires):
    source = Source(body)
    if control is not None:
        source.headers.append(("cache-control", control))
    reader = reader_for(client, clock, source)
    assert run(reader, client) == body
    clock.value += expires - 0.001
    assert run(reader, client) == body
    assert len(source.requests) == 1
    clock.value += 0.001
    assert run(reader, client) == body
    assert len(source.requests) == 2


@pytest.mark.parametrize(
    "control",
    [
        "no-store",
        "no-cache",
        "max-age=0",
        "max-age=bad",
        "max-age=60, max-age=50",
        "stale-if-error=300",
        "public, unsupported=30",
        "",
        'max-age="60"',
    ],
)
def test_noncacheable_response_is_current_read_only(client, clock, body, control):
    source = Source(body, [("content-type", "application/json"), ("cache-control", control)])
    reader = reader_for(client, clock, source)
    assert run(reader, client) == body
    assert run(reader, client) == body
    assert len(source.requests) == 2


def test_upstream_age_shortens_remaining_cache_life(client, clock, body):
    source = Source(body, [("content-type", "application/json"), ("age", "59")])
    reader = reader_for(client, clock, source)
    assert run(reader, client) == body
    clock.value = 101
    assert run(reader, client) == body
    assert len(source.requests) == 2


@pytest.mark.parametrize("age", ["60", "999999999", "-1", "01", "1.5", "nan", "9999999999"])
def test_stale_or_ambiguous_age_rejected(client, clock, body, age):
    source = Source(body, [("content-type", "application/json"), ("age", age)])
    with pytest.raises(AuthenticationUnavailable):
        run(reader_for(client, clock, source), client)


def test_no_stale_on_error_or_failed_freshness_extension(client, clock, body):
    source = Source(body)
    reader = reader_for(client, clock, source)
    assert run(reader, client) == body
    clock.value = 160
    source.status = 503
    for current in (160, 170, 189.999):
        clock.value = current
        with pytest.raises(AuthenticationUnavailable) as error:
            run(reader, client)
        assert str(error.value) == "Authentication is temporarily unavailable."
        assert error.value.__suppress_context__
    assert len(source.requests) == 2
    source.status = 200
    clock.value = 190
    assert run(reader, client) == body
    assert len(source.requests) == 3


@pytest.mark.parametrize("bad", [-1, 99, float("inf"), float("nan"), True, "100"])
def test_clock_uncertainty_clears_cache_and_latches_closed(client, clock, body, bad):
    source = Source(body)
    reader = reader_for(client, clock, source)
    assert run(reader, client) == body
    clock.value = bad
    with pytest.raises(AuthenticationUnavailable):
        run(reader, client)
    clock.value = 200
    with pytest.raises(AuthenticationUnavailable):
        run(reader, client)
    assert len(source.requests) == 1


def test_request_and_cleanup_time_count_towards_snapshot_age(client, clock, body):
    source = Source(body)
    original = source.respond

    async def slow_response(request):
        clock.value += 59
        return await original(request)

    source.respond = slow_response
    reader = reader_for(client, clock, source)
    assert run(reader, client) == body
    clock.value = 160
    assert run(reader, client) == body
    assert len(source.requests) == 2


def test_response_arriving_after_trust_lifetime_is_not_published(client, clock, body):
    source = Source(body)
    original = source.respond

    async def expired_response(request):
        clock.value += 60
        return await original(request)

    source.respond = expired_response
    with pytest.raises(AuthenticationUnavailable):
        run(reader_for(client, clock, source), client)


def test_cancelled_body_holds_custody_until_close_then_latches(client, clock, body):
    async def scenario():
        entered = asyncio.Event()
        closing = asyncio.Event()
        release = asyncio.Event()

        class Blocking(Chunks):
            async def __aiter__(self):
                entered.set()
                await asyncio.Event().wait()
                yield self.body

            async def aclose(self):
                closing.set()
                await release.wait()
                self.closed = True

        stream = Blocking(body)
        source = Source(body)

        async def handler(request):
            return httpx.Response(200, headers={"content-type": "application/json"}, stream=stream)

        reader = JwksReader(client, transport_factory=lambda: Transport(handler), clock=clock)
        task = asyncio.create_task(reader.read(client))
        await entered.wait()
        task.cancel()
        await closing.wait()
        competing = reader_for(client, clock, source)
        with pytest.raises(AuthenticationUnavailable):
            await competing.read(client)
        assert not source.requests
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert stream.closed
        with pytest.raises(AuthenticationUnavailable):
            await competing.read(client)
        with pytest.raises(AuthenticationUnavailable):
            await reader.read(client)
        assert all(pending.done() for pending in [task])

    asyncio.run(scenario())


def test_uncertain_client_cleanup_disables_new_network_admission(client, clock, body):
    async def scenario():
        closing = asyncio.Event()
        source = Source(body)

        class Uncertain(Transport):
            async def aclose(self):
                closing.set()
                await asyncio.Event().wait()

        reader = JwksReader(
            client, transport_factory=lambda: Uncertain(source.respond), clock=clock
        )
        task = asyncio.create_task(reader.read(client))
        await closing.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        with pytest.raises(AuthenticationUnavailable):
            await reader_for(client, clock, source).read(client)
        assert len(source.requests) == 1

    asyncio.run(scenario())


def test_slow_drip_reaches_overall_deadline_and_closes(monkeypatch, client, clock, body):
    monkeypatch.setattr(module, "READ_SECONDS", 0.015)

    class Drip(Chunks):
        async def __aiter__(self):
            for byte in self.body:
                await asyncio.sleep(0.004)
                yield bytes([byte])

    stream = Drip(body)

    async def handler(request):
        return httpx.Response(200, headers={"content-type": "application/json"}, stream=stream)

    reader = JwksReader(client, transport_factory=lambda: Transport(handler), clock=clock)
    with pytest.raises(AuthenticationUnavailable):
        run(reader, client)
    assert stream.closed


def test_cleanup_timeout_latches_gate_without_detached_tasks(monkeypatch, client, clock, body):
    monkeypatch.setattr(module, "_CLEANUP_SECONDS", 0.01)

    class Unclosed(Transport):
        async def aclose(self):
            await asyncio.Event().wait()

    source = Source(body)
    reader = JwksReader(client, transport_factory=lambda: Unclosed(source.respond), clock=clock)
    with pytest.raises(AuthenticationUnavailable):
        run(reader, client)
    with pytest.raises(AuthenticationUnavailable):
        run(reader_for(client, clock, source), client)
    assert len(source.requests) == 1


def test_snapshot_rotation_and_unknown_kid_never_trigger_fetch(client, clock, body, private):
    source = Source(body)
    reader = reader_for(client, clock, source)
    attempt = create_attempt(client, 1_800_000_000)
    claims = {
        "iss": client.issuer,
        "sub": "opaque-subject",
        "aud": client.client_id,
        "iat": 1_800_000_001,
        "exp": 1_800_000_100,
        "auth_time": 1_800_000_000,
        "nonce": attempt.nonce.get_secret_value(),
        "amr": ["pwd", "otp", "mfa"],
    }

    def compact(kid):
        return SecretStr(
            jwt.encode({"alg": "RS256", "kid": kid}, claims, RSAKey.import_key(private))
        )

    snapshot = run(reader, client)
    assert verify_id_token(compact("old"), snapshot, attempt, 1_800_000_002)
    with pytest.raises(AuthenticationDenied):
        verify_id_token(compact("unknown"), run(reader, client), attempt, 1_800_000_002)
    assert len(source.requests) == 1
    keys = json.loads(body)
    keys["keys"][0]["kid"] = "new"
    source.body = json.dumps(keys).encode()
    clock.value = 160
    snapshot = run(reader, client)
    with pytest.raises(AuthenticationDenied):
        verify_id_token(compact("old"), snapshot, attempt, 1_800_000_002)
    assert verify_id_token(compact("new"), snapshot, attempt, 1_800_000_002)
    assert len(source.requests) == 2


def test_failure_canaries_stay_out_of_public_errors_repr_and_safe_logs(client, clock, caplog):
    canary = "CANARY_PROVIDER_BODY_OR_CREDENTIAL"
    source = Source(canary.encode())
    source.failure = httpx.ConnectError(canary)
    reader = reader_for(client, clock, source)
    with caplog.at_level(logging.DEBUG), pytest.raises(AuthenticationUnavailable) as error:
        run(reader, client)
    rendered = str(error.value) + repr(error.value) + repr(reader)
    record = logging.LogRecord("httpx2", logging.INFO, "", 0, "HTTP request %s", (canary,), None)
    rendered += SafeFormatter().format(record)
    rendered += "".join(SafeFormatter().format(item) for item in caplog.records)
    assert canary not in rendered
    assert client.jwks_uri not in rendered


@pytest.fixture(autouse=True)
def forbid_real_transport(monkeypatch):
    attempted = []
    original = httpx.AsyncHTTPTransport.handle_async_request

    async def guarded(self, request):
        # Exercise real parsing only over the explicit no-socket backend below.
        if isinstance(self._pool._network_backend, NoSocketBackend):
            return await original(self, request)
        attempted.append(request)
        raise AssertionError("A synthetic test reached a socket-capable transport.")

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", guarded)
    yield
    assert not attempted


def test_cold_reads_do_not_queue_and_header_cancellation_closes(client, clock, body):
    async def scenario():
        entered = asyncio.Event()
        source = Source(body)
        transports = []

        async def pending(request):
            entered.set()
            await asyncio.Event().wait()

        def factory():
            transport = Transport(pending)
            transports.append(transport)
            return transport

        reader = JwksReader(client, transport_factory=factory, clock=clock)
        task = asyncio.create_task(reader.read(client))
        await entered.wait()
        competing = reader_for(client, clock, source)
        attempts = await asyncio.gather(
            *(competing.read(client) for _ in range(12)), return_exceptions=True
        )
        assert all(type(error) is AuthenticationUnavailable for error in attempts)
        assert not source.requests
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert all(transport.closed for transport in transports)
        with pytest.raises(AuthenticationUnavailable):
            await competing.read(client)

    asyncio.run(scenario())


def test_fresh_cache_does_not_wait_for_other_network_custody(client, clock, body):
    async def scenario():
        source = Source(body)
        cached = reader_for(client, clock, source)
        assert await cached.read(client) == body
        entered = asyncio.Event()

        async def pending(request):
            entered.set()
            await asyncio.Event().wait()

        other = JwksReader(client, transport_factory=lambda: Transport(pending), clock=clock)
        task = asyncio.create_task(other.read(client))
        await entered.wait()
        assert await cached.read(client) == body
        assert len(source.requests) == 1
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())


def test_response_cookie_is_cleared_and_never_reused(monkeypatch, client, clock, body):
    source = Source(body, [("content-type", "application/json"), ("set-cookie", "private=canary")])
    original = httpx.AsyncClient
    clients = []

    def capture(**kwargs):
        instance = original(**kwargs)
        clients.append(instance)
        return instance

    monkeypatch.setattr(module.httpx, "AsyncClient", capture)
    reader = reader_for(client, clock, source)
    with pytest.raises(AuthenticationUnavailable):
        run(reader, client)
    assert clients[0].is_closed and not clients[0].cookies
    clock.value = 130
    source.headers = [("content-type", "application/json")]
    assert run(reader, client) == body
    assert len(clients) == 2
    assert "cookie" not in source.requests[-1].headers


def test_noncacheable_upstream_aged_keys_are_rejected(client, clock, body):
    source = Source(
        body, [("content-type", "application/json"), ("cache-control", "no-store"), ("age", "1")]
    )
    with pytest.raises(AuthenticationUnavailable):
        run(reader_for(client, clock, source), client)


def test_cache_expiry_still_applies_to_invalid_refresh(client, clock, body):
    source = Source(body)
    reader = reader_for(client, clock, source)
    assert run(reader, client) == body
    source.body = b'{"keys":[]}'
    clock.value = 160
    with pytest.raises(AuthenticationUnavailable):
        run(reader, client)
    source.body = body
    clock.value = 189.999
    with pytest.raises(AuthenticationUnavailable):
        run(reader, client)
    assert len(source.requests) == 2
    clock.value = 190
    assert run(reader, client) == body


def test_clock_failure_after_fetch_cannot_publish_keys(client, clock, body):
    source = Source(body)
    original = source.respond

    async def failure_after_admission(request):
        response = await original(request)
        clock.value = float("nan")
        return response

    source.respond = failure_after_admission
    reader = reader_for(client, clock, source)
    with pytest.raises(AuthenticationUnavailable):
        run(reader, client)
    clock.value = 200
    with pytest.raises(AuthenticationUnavailable):
        run(reader, client)
    assert len(source.requests) == 1


def test_clock_exception_is_sanitized_before_network(client, body):
    def broken_clock():
        raise RuntimeError("CANARY_CLOCK_SOURCE")

    source = Source(body)
    reader = JwksReader(client, transport_factory=source.factory, clock=broken_clock)
    with pytest.raises(AuthenticationUnavailable) as error:
        run(reader, client)
    assert "CANARY" not in str(error.value)
    assert error.value.__suppress_context__
    assert not source.requests


def test_production_transport_has_verified_tls_and_no_proxy_retry_pool(monkeypatch, client):
    import ssl

    for variable in ("HTTPS_PROXY", "ALL_PROXY", "SSL_CERT_FILE", "SSL_CERT_DIR"):
        monkeypatch.setenv(variable, "canary-invalid-environment")
    owned = JwksReader(client)._new_client()
    try:
        pool = owned._transport._pool
        assert pool._retries == 0
        assert pool._max_connections == 1
        assert pool._max_keepalive_connections == 0
        assert pool._http2 is False
        assert pool._ssl_context.check_hostname is True
        assert pool._ssl_context.verify_mode == ssl.CERT_REQUIRED
        assert not owned._mounts
    finally:
        asyncio.run(owned.aclose())


def test_cleanup_error_is_private_and_latches_admission(client, clock, body):
    source = Source(body)

    class FailedClose(Transport):
        async def aclose(self):
            raise RuntimeError("CANARY_CLOSE_FAILURE")

    reader = JwksReader(client, transport_factory=lambda: FailedClose(source.respond), clock=clock)
    with pytest.raises(AuthenticationUnavailable) as error:
        run(reader, client)
    assert "CANARY" not in str(error.value)
    assert error.value.__suppress_context__
    with pytest.raises(AuthenticationUnavailable):
        run(reader_for(client, clock, source), client)
    assert len(source.requests) == 1


def test_stream_close_failure_cannot_hide_behind_response_closed_flag(client, clock, body):
    source = Source(body)

    class FailedStream(Chunks):
        async def aclose(self):
            raise RuntimeError("CANARY_STREAM_CLOSE")

    async def handler(request):
        return httpx.Response(
            200, headers={"content-type": "application/json"}, stream=FailedStream(body)
        )

    reader = JwksReader(client, transport_factory=lambda: Transport(handler), clock=clock)
    with pytest.raises(AuthenticationUnavailable) as error:
        run(reader, client)
    assert "CANARY" not in str(error.value)
    with pytest.raises(AuthenticationUnavailable):
        run(reader_for(client, clock, source), client)
    assert not source.requests


def test_oversized_body_closes_raw_iterator_in_same_task(client, clock):
    async def scenario():
        caller = asyncio.current_task()
        finished = []

        class Oversized(Chunks):
            async def __aiter__(self):
                try:
                    yield b"x" * 65537
                finally:
                    finished.append(asyncio.current_task())

        stream = Oversized(b"")

        async def handler(request):
            return httpx.Response(200, headers={"content-type": "application/json"}, stream=stream)

        reader = JwksReader(client, transport_factory=lambda: Transport(handler), clock=clock)
        with pytest.raises(AuthenticationUnavailable):
            await reader.read(client)
        assert finished == [caller]
        assert stream.closed

    asyncio.run(scenario())


class NoSocketStream(AsyncNetworkStream):
    def __init__(self, backend):
        self.backend = backend
        self.wire = bytearray(backend.wire)
        self.close_calls = 0
        self.closed = False

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
        assert kwargs["host"] == "identity.example.test"
        assert kwargs["port"] == 443
        stream = NoSocketStream(self)
        self.streams.append(stream)
        return stream

    async def connect_unix_socket(self, **kwargs):
        raise AssertionError("Unix sockets are outside the test contract.")

    async def sleep(self, seconds):
        raise AssertionError("Retries are outside the test contract.")

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


@pytest.mark.parametrize("phase", ["headers", "body"])
@pytest.mark.parametrize("close_error", [False, True])
def test_real_transport_ambiguous_read_failure_latches_even_if_later_close_succeeds(
    client, clock, phase, close_error
):
    wire = b""
    if phase == "body":
        wire = b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 100\r\n\r\n"
    backend = NoSocketBackend(wire, read_error=True, close_error=close_error)
    reader = JwksReader(client, transport_factory=backend.factory, clock=clock)
    with pytest.raises(AuthenticationUnavailable) as error:
        run(reader, client)
    assert "CANARY" not in str(error.value)
    assert module._GATE._disabled is True
    assert module._GATE._busy is False
    assert len(backend.streams) == 1
    assert backend.streams[0].close_calls == 1
    clock.value = 1000
    replacement = JwksReader(client, transport_factory=backend.factory, clock=clock)
    with pytest.raises(AuthenticationUnavailable):
        run(replacement, client)
    assert len(backend.streams) == 1


@pytest.mark.parametrize("phase", ["headers", "body"])
@pytest.mark.parametrize("close_error", [False, True])
def test_real_transport_cancellation_survives_hidden_cleanup_error_and_latches(
    client, clock, phase, close_error
):
    async def scenario():
        wire = b""
        if phase == "body":
            wire = (
                b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 100\r\n\r\n"
            )
        backend = NoSocketBackend(wire, close_error=close_error, block=True)
        reader = JwksReader(client, transport_factory=backend.factory, clock=clock)
        task = asyncio.create_task(reader.read(client))
        await backend.entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert task.cancelled()
        assert module._GATE._disabled is True
        assert module._GATE._busy is False
        assert backend.streams[0].close_calls == 1
        replacement = JwksReader(client, transport_factory=backend.factory, clock=clock)
        with pytest.raises(AuthenticationUnavailable):
            await replacement.read(client)
        assert len(backend.streams) == 1

    asyncio.run(scenario())


@pytest.mark.parametrize("form", ["twice", "comma", "many"])
def test_real_parser_normalizes_equivalent_content_lengths_before_application_checks(
    client, clock, body, form
):
    length = str(len(body)).encode()
    if form == "comma":
        fields = b"Content-Length: " + length + b", " + length + b"\r\n"
    else:
        fields = (b"Content-Length: " + length + b"\r\n") * (1000 if form == "many" else 2)
    wire = b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n" + fields + b"\r\n" + body
    if form == "many":
        assert len(fields) > 16384
    backend = NoSocketBackend(wire)
    reader = JwksReader(client, transport_factory=backend.factory, clock=clock)
    assert run(reader, client) == body
    assert backend.streams[0].closed
    assert module._GATE._disabled is False


def test_real_parser_rejects_conflicting_content_lengths(client, clock, body):
    fields = f"Content-Length: {len(body)}\r\nContent-Length: {len(body) + 1}\r\n".encode()
    backend = NoSocketBackend(
        b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n" + fields + b"\r\n" + body
    )
    with pytest.raises(AuthenticationUnavailable):
        run(JwksReader(client, transport_factory=backend.factory, clock=clock), client)
    assert backend.streams[0].closed
    assert module._GATE._disabled is True


def test_real_parser_preserves_duplicate_media_fields_for_application_rejection(
    client, clock, body
):
    wire = (
        b"HTTP/1.1 200 OK\r\n"
        b"Content-Type: application/json\r\nContent-Type: application/json\r\n"
        + f"Content-Length: {len(body)}\r\n\r\n".encode()
        + body
    )
    backend = NoSocketBackend(wire)
    with pytest.raises(AuthenticationUnavailable):
        run(JwksReader(client, transport_factory=backend.factory, clock=clock), client)
    assert backend.streams[0].closed
    assert module._GATE._disabled is False


@pytest.mark.parametrize("phase", ["headers", "body"])
@pytest.mark.parametrize("close_error", [False, True])
def test_real_transport_deadline_latches_even_when_hidden_close_replaces_timeout(
    monkeypatch, client, clock, phase, close_error
):
    monkeypatch.setattr(module, "READ_SECONDS", 0.01)
    wire = b""
    if phase == "body":
        wire = b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 100\r\n\r\n"
    backend = NoSocketBackend(wire, close_error=close_error, block=True)
    reader = JwksReader(client, transport_factory=backend.factory, clock=clock)
    with pytest.raises(AuthenticationUnavailable):
        run(reader, client)
    assert module._GATE._disabled is True
    assert module._GATE._busy is False
    assert len(backend.streams) == 1
    assert backend.streams[0].close_calls == 1
    with pytest.raises(AuthenticationUnavailable):
        run(JwksReader(client, transport_factory=backend.factory, clock=clock), client)
    assert len(backend.streams) == 1
