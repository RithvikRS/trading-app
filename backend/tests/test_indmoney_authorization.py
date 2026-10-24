import asyncio
import base64
import hashlib
import json
import secrets
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import httpx2 as httpx
import pytest
from pydantic import SecretStr, ValidationError
from starlette.requests import Request

from tests.indmoney_support import ACCESS, CODE, REFRESH, IndmoneyStub
from trading_api.authentication import CookiePolicy
from trading_api.config import ConfigurationError, Settings, load_settings
from trading_api.indmoney import CALLBACK_COOKIE, callback_values
from trading_connectors.indmoney_keys import ConnectorKeys
from trading_connectors.indmoney_models import (
    CALLBACK,
    ClientRegistration,
    ConnectorRejected,
    ConnectorUnavailable,
)
from trading_connectors.indmoney_provider import IndmoneyProvider


def test_pkce_scope_resource_client_auth_and_token_privacy():
    stub = IndmoneyStub()
    provider = stub.provider()
    pkce, state = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    url = urlsplit(provider.authorization_url(state, pkce))
    assert url.scheme == "https" and url.netloc == "mcp.indmoney.com" and url.path == "/authorize"
    params = parse_qs(url.query)
    assert params["redirect_uri"] == [CALLBACK]
    assert params["resource"] == ["https://mcp.indmoney.com/mcp"]
    assert params["scope"] == ["portfolio:read"] and params["state"] == [state]
    assert params["code_challenge"] == [
        base64.urlsafe_b64encode(hashlib.sha256(pkce.encode()).digest()).rstrip(b"=").decode()
    ]
    tokens = asyncio.run(provider.exchange(SecretStr(CODE), SecretStr(pkce)))
    request = stub.requests[-1]
    assert request.headers["authorization"].startswith("Basic ")
    body = parse_qs(request.content.decode())
    assert body["code_verifier"] == [pkce] and body["code"] == [CODE]
    assert "client_secret" not in body and "cookie" not in request.headers
    for value in (ACCESS, REFRESH, CODE, pkce, "synthetic-client-secret"):
        assert value not in repr(tokens) + repr(provider) + repr(provider.client)
    renewed = asyncio.run(provider.refresh(tokens))
    assert renewed.refresh_token != tokens.refresh_token
    asyncio.run(provider.revoke(renewed))
    assert stub.revocations == 2


@pytest.mark.parametrize(
    "change",
    [
        {"scope": "portfolio:read market:read"},
        {"scope": "orders:write"},
        {"token_type": "mac"},
        {"expires_in": 0},
        {"expires_in": True},
        {"expires_in": "3600"},
        {"expires_in": 86401},
        {"resource": "https://attacker.invalid/mcp"},
        {"issuer": "https://attacker.invalid/"},
        {"access_token": "\r\nprivate-value-here"},
        {"refresh_token": "short"},
        {"id_token": "unexpected"},
    ],
)
def test_unverified_grants_and_bad_tokens_are_rejected(change):
    stub = IndmoneyStub()
    raw = (
        dict(
            access_token=ACCESS,
            refresh_token=REFRESH,
            scope="portfolio:read",
            token_type="Bearer",
            expires_in=3600,
        )
        | change
    )
    stub.override = lambda _: httpx.Response(
        200,
        stream=httpx.ByteStream(json.dumps(raw).encode()),
        headers={"content-type": "application/json"},
    )
    with pytest.raises(ConnectorUnavailable) as error:
        asyncio.run(stub.provider().exchange(SecretStr(CODE), SecretStr("a" * 43)))
    assert "synthetic" not in str(error.value)
    assert len(stub.requests) == 1


@pytest.mark.parametrize(
    "raw",
    [
        b"[]",
        b"\xff",
        b'{"expires_in":1,"expires_in":2}',
        b'{"expires_in":NaN}',
        b'{"expires_in":1.1}',
        b'{"nested":{}}',
        b"a" * 32769,
        b"[" * 1200,
    ],
    ids=["array", "encoding", "duplicate", "nonfinite", "float", "nested", "large", "deep"],
)
def test_token_documents_are_bounded_strict_and_not_echoed(raw):
    stub = IndmoneyStub()
    stub.override = lambda _: httpx.Response(
        200, stream=httpx.ByteStream(raw), headers={"content-type": "application/json"}
    )
    with pytest.raises(ConnectorUnavailable):
        asyncio.run(stub.provider().exchange(SecretStr(CODE), SecretStr("a" * 43)))


@pytest.mark.parametrize(
    "status,headers",
    [
        (302, {"location": "https://attacker.invalid"}),
        (401, {}),
        (429, {}),
        (500, {}),
        (200, {"content-type": "text/html"}),
        (200, {"content-type": "application/json", "content-encoding": "gzip"}),
    ],
)
def test_transport_errors_never_follow_redirect_or_retry(status, headers):
    stub = IndmoneyStub()
    stub.override = lambda _: httpx.Response(
        status, stream=httpx.ByteStream(b"private-error"), headers=headers
    )
    with pytest.raises(ConnectorUnavailable, match="^Connection unavailable"):
        asyncio.run(stub.provider().exchange(SecretStr(CODE), SecretStr("a" * 43)))
    assert len(stub.requests) == 1


def test_ciphertext_context_tampering_rotation_and_missing_keys():
    first, second = secrets.token_bytes(32), secrets.token_bytes(32)
    keys = ConnectorKeys({1: first}, 1)
    owner, connection = uuid4(), uuid4()
    sealed = keys.seal(owner, connection, "tokens", 1, b"synthetic-secret")
    assert b"synthetic-secret" not in sealed
    for args in [
        (uuid4(), connection, "tokens", 1),
        (owner, uuid4(), "tokens", 1),
        (owner, connection, "attempt", 1),
        (owner, connection, "tokens", 2),
    ]:
        with pytest.raises(ConnectorUnavailable):
            keys.open(*args, sealed)
    with pytest.raises(ConnectorUnavailable):
        keys.open(owner, connection, "tokens", 1, sealed[:-1] + bytes([sealed[-1] ^ 1]))
    rotated = ConnectorKeys({1: first, 2: second}, 2)
    raw = rotated.open(owner, connection, "tokens", 1, sealed)
    new = rotated.seal(owner, connection, "tokens", 1, raw)
    assert ConnectorKeys({2: second}, 2).open(owner, connection, "tokens", 1, new) == raw
    with pytest.raises(ConnectorUnavailable):
        ConnectorKeys({2: second}, 2).open(owner, connection, "tokens", 1, sealed)
    assert "synthetic-secret" not in repr(keys)


def callback(query=None, extra=None):
    return Request(
        dict(
            type="http",
            method="GET",
            path="/api/v1/connections/indmoney/callback",
            root_path="",
            scheme="https",
            server=("127.0.0.1", 8443),
            query_string=query or ("state=" + "s" * 43 + "&code=" + CODE).encode(),
            headers=[
                (b"host", b"127.0.0.1:8443"),
                (b"cookie", (CALLBACK_COOKIE + "=" + "b" * 43).encode()),
            ]
            + (extra or []),
        )
    )


@pytest.mark.parametrize(
    "query,extra",
    [
        (b"state=x&code=x", []),
        (("state=" + "s" * 43 + "&code=a&code=b").encode(), []),
        (("state=" + "s" * 43 + "&code=a&error=b").encode(), []),
        (("state=" + "s" * 43 + "&code=%zz").encode(), []),
        (("state=" + "s" * 43 + "&code=%0a").encode(), []),
        (b"x" * 8193, []),
        (None, [(b"authorization", b"Bearer private")]),
        (None, [(b"sec-fetch-mode", b"cors")]),
        (None, [(b"sec-fetch-dest", b"iframe")]),
        (None, [(b"cookie", (CALLBACK_COOKIE + "=" + "b" * 43).encode())]),
        (None, [(b"host", b"attacker.invalid")]),
        (None, [(b"content-length", b"1")]),
    ],
)
def test_callback_rejects_ambiguity_and_non_navigation(query, extra):
    with pytest.raises(ConnectorRejected):
        callback_values(callback(query, extra), CookiePolicy("https://127.0.0.1:8443", secure=True))


def test_callback_only_returns_private_code_to_server_and_configuration_is_fail_closed():
    values = callback_values(callback(), CookiePolicy("https://127.0.0.1:8443", secure=True))
    assert values[2].get_secret_value() == CODE
    assert CODE not in repr(values)
    for environ in (
        {"TRADING_API_INDMONEY_ENABLED": "true"},
        {"TRADING_API_HTTPS_ENABLED": "true"},
        {"TRADING_API_INDMONEY_ENABLED": "yes"},
    ):
        with pytest.raises(ConfigurationError):
            load_settings(environ)
    assert Settings(https_enabled=True, port=8443, auth_enabled=True, indmoney_enabled=True)
    with pytest.raises(ValidationError):
        ClientRegistration(
            client_id=SecretStr("id"),
            client_secret=SecretStr("x" * 32),
            callback="https://attacker.invalid",
        )


def test_form_encoded_basic_credentials():
    stub = IndmoneyStub()
    secret = secrets.token_urlsafe(24)
    client = ClientRegistration(
        client_id=SecretStr("id:with+symbols"), client_secret=SecretStr(secret + ":+")
    )
    provider = IndmoneyProvider(client, transport=httpx.MockTransport(stub.handle))
    asyncio.run(provider.exchange(SecretStr(CODE), SecretStr("a" * 43)))
    decoded = base64.b64decode(
        stub.requests[0].headers["authorization"].removeprefix("Basic ")
    ).decode()
    assert decoded == "id%3Awith%2Bsymbols:" + secret + "%3A%2B"


@pytest.mark.parametrize(
    "headers",
    [
        [("content-type", "application/json"), ("content-type", "application/json")],
        [("content-type", "application/json"), ("content-length", "999999")],
        [("content-type", "application/json"), ("content-length", "1")],
        [("content-type", "application/json"), ("content-length", "-1")],
    ],
)
def test_token_response_headers_are_unambiguous_and_match_the_body(headers):
    stub = IndmoneyStub()
    stub.override = lambda _: httpx.Response(200, stream=httpx.ByteStream(b"{}"), headers=headers)
    with pytest.raises(ConnectorUnavailable):
        asyncio.run(stub.provider().exchange(SecretStr(CODE), SecretStr("a" * 43)))


def test_explicit_key_loading_never_creates_or_prints_credentials(tmp_path, monkeypatch, capsys):
    from trading_connectors import local

    monkeypatch.setattr(local, "DIRECTORY", tmp_path)
    with pytest.raises(ConnectorUnavailable):
        local.load_keys()
    assert not list(tmp_path.iterdir())
    (tmp_path / "keys").mkdir(mode=0o700)
    path = tmp_path / "keys/v1.key"
    path.write_bytes(secrets.token_bytes(32))
    path.chmod(0o600)
    keys = local.load_keys()
    client = ClientRegistration(
        client_id=SecretStr("synthetic-client"),
        client_secret=SecretStr("synthetic-client-secret-123"),
    )
    raw = keys.seal(None, None, "client", 1, client.private_bytes())
    assert b"synthetic-client-secret" not in raw
    assert ClientRegistration.model_validate_json(keys.open(None, None, "client", 1, raw)) == client
    monkeypatch.setenv("TRADING_INDMONEY_KEY_VERSIONS", "1,2")
    with pytest.raises(ConnectorUnavailable):
        local.load_keys()
    monkeypatch.setenv("TRADING_INDMONEY_KEY_VERSIONS", "1")
    monkeypatch.setenv("TRADING_INDMONEY_CLIENT_SECRET", "synthetic-not-allowed")
    with pytest.raises(ConnectorUnavailable):
        local.load_keys()
    assert "synthetic" not in capsys.readouterr().out


@pytest.mark.parametrize(
    "versions", [{}, {1: b"x" * 32, "2": b"y" * 32}, {True: b"x" * 32}, {1: b"short"}]
)
def test_malformed_key_rings_fail_with_a_sanitized_error(versions):
    with pytest.raises(ConnectorUnavailable, match="^Connection unavailable.$"):
        ConnectorKeys(versions, 1)


def test_overall_deadline_cancels_a_stalled_response_without_retry(monkeypatch):
    import trading_connectors.indmoney_provider as module

    timeout = asyncio.timeout
    deadlines = []

    def short_deadline(seconds):
        deadlines.append(seconds)
        return timeout(0.02)

    class Stalled(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"{"
            await asyncio.sleep(60)

    stub = IndmoneyStub()
    stub.override = lambda _: httpx.Response(
        200, stream=Stalled(), headers={"content-type": "application/json"}
    )
    monkeypatch.setattr(module.asyncio, "timeout", short_deadline)
    with pytest.raises(ConnectorUnavailable):
        asyncio.run(stub.provider().exchange(SecretStr(CODE), SecretStr("a" * 43)))
    assert deadlines == [10] and len(stub.requests) == 1
