"""Synthetic INDmoney transport: no provider connection or account data."""

import json
from urllib.parse import parse_qs

import httpx2 as httpx
from pydantic import SecretStr

from tests.test_indmoney_discovery import documents
from trading_connectors.indmoney_models import ClientRegistration
from trading_connectors.indmoney_provider import IndmoneyProvider

ACCESS = "synthetic-indmoney-access-value-only"
REFRESH = "synthetic-indmoney-refresh-value-only"
CODE = "synthetic-authorization-code"


class IndmoneyStub:
    def __init__(self):
        self.requests = []
        self.hook = None
        self.override = None
        self.refreshes = 0
        self.revocations = 0
        self.fail_revoke = False
        self.issuer_required = False

    def handle(self, request):
        self.requests.append(request)
        if request.method == "GET":
            values = documents()
            document = values[0] if "oauth-protected-resource" in request.url.path else values[1]
            if self.issuer_required and document is values[1]:
                document["authorization_response_iss_parameter_supported"] = True
            return httpx.Response(
                200,
                stream=httpx.ByteStream(json.dumps(document).encode()),
                headers={"content-type": "application/json"},
            )
        if request.url.path == "/revoke":
            self.revocations += 1
            return httpx.Response(503 if self.fail_revoke else 200, stream=httpx.ByteStream(b""))
        assert request.url.path == "/token"
        data = parse_qs(request.content.decode())
        if data["grant_type"] == ["refresh_token"]:
            self.refreshes += 1
        if self.hook:
            self.hook()
        if self.override:
            return self.override(request)
        return httpx.Response(
            200,
            stream=httpx.ByteStream(
                json.dumps(
                    dict(
                        access_token=ACCESS + str(self.refreshes),
                        refresh_token=REFRESH + str(self.refreshes),
                        scope="portfolio:read",
                        token_type="Bearer",
                        expires_in=3600,
                    )
                ).encode()
            ),
            headers={"content-type": "application/json"},
        )

    def provider(self):
        return IndmoneyProvider(
            ClientRegistration(
                client_id=SecretStr("synthetic-local-client"),
                client_secret=SecretStr("synthetic-client-secret-value-only"),
            ),
            transport=httpx.MockTransport(self.handle),
        )
