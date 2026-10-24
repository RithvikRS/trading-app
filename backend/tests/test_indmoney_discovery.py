import asyncio
import json

import httpx2 as httpx
import pytest

from trading_connectors import indmoney_discovery as discovery


def documents():
    return {
        "resource": discovery.RESOURCE,
        "authorization_servers": [discovery.ISSUER],
        "scopes_supported": ["portfolio:read"],
        "bearer_methods_supported": ["header"],
    }, {
        "issuer": discovery.ISSUER,
        "authorization_endpoint": discovery.ISSUER + "authorize",
        "token_endpoint": discovery.ISSUER + "token",
        "registration_endpoint": discovery.ISSUER + "register",
        "scopes_supported": ["portfolio:read", "market:read"],
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "token_endpoint_auth_methods_supported": ["client_secret_post", "client_secret_basic"],
        "service_documentation": "https://www.indmoney.com/mcp",
        "revocation_endpoint": discovery.ISSUER + "revoke",
        "revocation_endpoint_auth_methods_supported": ["client_secret_basic"],
        "code_challenge_methods_supported": ["S256"],
    }


def encode(value):
    return json.dumps(value).encode()


def response(body, *, status=200, headers=None):
    return httpx.Response(
        status,
        headers=headers if headers is not None else {"content-type": "application/json"},
        stream=httpx.ByteStream(body),
    )


def test_discovery_is_non_authorizing_and_preserves_optional_capability_absence():
    resource, server = documents()
    assert discovery.validate_metadata(
        encode(resource), encode(server)
    ) == discovery.DiscoveryEvidence(
        refresh_advertised=True, registration_advertised=True, response_issuer_advertised=False
    )
    del server["registration_endpoint"]
    server["grant_types_supported"] = ["authorization_code"]
    server["authorization_response_iss_parameter_supported"] = True
    assert discovery.validate_metadata(
        encode(resource), encode(server)
    ) == discovery.DiscoveryEvidence(
        refresh_advertised=False, registration_advertised=False, response_issuer_advertised=True
    )


@pytest.mark.parametrize("document", [0, 1])
@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"[]",
        b"null",
        b"\xff",
        b"\xef\xbb\xbf{}",
        b'{"duplicate":1,"duplicate":2}',
        b'{"duplicate":"x","duplicate":"y"}',
        b'{"number":NaN}',
        b'{"number":1.1}',
        b'{"number":1}',
        b"[" * 1100 + b"]" * 1100,
        b" " * (discovery.MAX_DOCUMENT_BYTES + 1),
        b"{} trailing",
        b'{"nested":{"x":true,"x":false}}',
    ],
)
def test_untrusted_documents_fail_with_fixed_diagnostics(document, raw):
    bodies = list(map(encode, documents()))
    bodies[document] = raw
    with pytest.raises(discovery.DiscoveryUnavailable, match="^INDmoney discovery is unavailable"):
        discovery.validate_metadata(*bodies)


@pytest.mark.parametrize(
    "key",
    [
        "issuer",
        "authorization_endpoint",
        "token_endpoint",
        "registration_endpoint",
        "revocation_endpoint",
    ],
)
@pytest.mark.parametrize(
    "target",
    [
        "https://other.invalid/token",
        "https://mcp.indmoney.com@other.invalid/token",
        "http://mcp.indmoney.com/token",
        "https://mcp.indmoney.com/token?forward=1",
        "https://mcp.indmoney.com:443/token",
    ],
)
def test_provider_destinations_cannot_be_substituted_or_normalized(key, target):
    resource, server = documents()
    server[key] = target
    with pytest.raises(discovery.DiscoveryUnavailable):
        discovery.validate_metadata(encode(resource), encode(server))


@pytest.mark.parametrize(
    "document,key,value",
    [
        (0, "resource", "https://mcp.indmoney.com/"),
        (0, "authorization_servers", [discovery.ISSUER, "https://other.invalid/"]),
        (0, "scopes_supported", ["portfolio:read", "trade:write"]),
        (0, "bearer_methods_supported", ["query"]),
        (1, "scopes_supported", ["portfolio:read", "trade:write"]),
        (1, "scopes_supported", ["market:read"]),
        (1, "scopes_supported", ["portfolio:read", "portfolio:read"]),
        (1, "scopes_supported", [["portfolio:read"]]),
        (1, "scopes_supported", "portfolio:read"),
        (1, "code_challenge_methods_supported", ["plain"]),
        (1, "code_challenge_methods_supported", []),
        (1, "code_challenge_methods_supported", None),
        (1, "grant_types_supported", ["client_credentials"]),
        (1, "response_types_supported", ["token"]),
        (1, "token_endpoint_auth_methods_supported", ["none"]),
        (1, "revocation_endpoint_auth_methods_supported", []),
        (1, "authorization_response_iss_parameter_supported", "true"),
        (1, "unreviewed_extension", True),
    ],
)
def test_capability_changes_require_review(document, key, value):
    docs = documents()
    docs[document][key] = value
    with pytest.raises(discovery.DiscoveryUnavailable):
        discovery.validate_metadata(*map(encode, docs))


def test_discovery_fetches_only_fixed_public_documents_without_ambient_credentials(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "https://other.invalid/")
    monkeypatch.setenv("SSL_CERT_FILE", "does-not-exist.pem")
    monkeypatch.setenv("INDMONEY_TOKEN", "synthetic-ignored-credential")
    calls = []

    def handle(request):
        calls.append(request)
        assert request.method == "GET"
        assert not request.content
        for header in ("authorization", "cookie", "proxy-authorization"):
            assert header not in request.headers
        assert request.headers["accept-encoding"] == "identity"
        return response(
            encode(documents()[len(calls) - 1]),
            headers={"content-type": "application/json; charset=utf-8", "set-cookie": "tracking=1"},
        )

    result = asyncio.run(discovery.discover(transport=httpx.MockTransport(handle)))
    assert result.refresh_advertised
    assert [str(call.url) for call in calls] == [
        discovery.RESOURCE_METADATA,
        discovery.SERVER_METADATA,
    ]


@pytest.mark.parametrize("status", [301, 302, 307, 308, 400, 401, 403, 404, 429, 500])
def test_failed_or_redirected_discovery_never_follows_or_retries(status):
    calls = []

    def handle(request):
        calls.append(request)
        return response(
            b"private-error-marker", status=status, headers={"location": "https://other.invalid/"}
        )

    with pytest.raises(discovery.DiscoveryUnavailable) as error:
        asyncio.run(discovery.discover(transport=httpx.MockTransport(handle)))
    assert len(calls) == 1
    assert "private-error-marker" not in str(error.value)


@pytest.mark.parametrize(
    "body,headers",
    [
        (b"{}", {}),
        (b"{}", {"content-type": "text/html"}),
        (b"{}", [("content-type", "application/json"), ("content-type", "application/json")]),
        (b"{}", {"content-type": "application/json", "content-encoding": "gzip"}),
        (b"{}", {"content-type": "application/json", "content-length": "99999"}),
        (b"{}", {"content-type": "application/json", "content-length": "-1"}),
        (b"{}", {"content-type": "application/json", "content-length": "3"}),
        (b"x" * (discovery.MAX_DOCUMENT_BYTES + 1), {"content-type": "application/json"}),
    ],
)
def test_transport_rejects_ambiguous_compressed_or_oversized_responses(body, headers):
    with pytest.raises(discovery.DiscoveryUnavailable):
        asyncio.run(
            discovery.discover(
                transport=httpx.MockTransport(lambda _: response(body, headers=headers))
            )
        )


def test_whole_attempt_timeout_cancels_slow_response_and_closes_transport(monkeypatch):
    monkeypatch.setattr(discovery, "DISCOVERY_SECONDS", 0.01)
    closed = []

    class Slow(httpx.AsyncByteStream):
        async def __aiter__(self):
            await asyncio.sleep(1)
            yield b"{}"

        async def aclose(self):
            closed.append(True)

    with pytest.raises(discovery.DiscoveryUnavailable):
        asyncio.run(
            discovery.discover(
                transport=httpx.MockTransport(
                    lambda _: httpx.Response(
                        200, headers={"content-type": "application/json"}, stream=Slow()
                    )
                )
            )
        )
    assert closed == [True]


def test_explicit_cancellation_is_not_swallowed():
    async def handle(_):
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(discovery.discover(transport=httpx.MockTransport(handle)))


def test_transport_errors_do_not_expose_diagnostics():
    def handle(_):
        raise httpx.ConnectError("synthetic-sensitive-marker")

    with pytest.raises(discovery.DiscoveryUnavailable) as error:
        asyncio.run(discovery.discover(transport=httpx.MockTransport(handle)))
    assert "synthetic-sensitive-marker" not in str(error.value)
