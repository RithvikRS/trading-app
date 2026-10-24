"""Fixed-destination OAuth requests with bounded transport; never follows redirects."""

import asyncio
import base64
import hashlib
from urllib.parse import quote_plus, urlencode

import httpx2 as httpx
from pydantic import SecretStr, ValidationError

from trading_connectors.indmoney_discovery import ISSUER, RESOURCE, DiscoveryEvidence, discover
from trading_connectors.indmoney_models import (
    CALLBACK,
    SCOPE,
    ClientRegistration,
    ConnectorUnavailable,
    TokenSecrets,
    private_document,
)


class IndmoneyProvider:
    def __init__(
        self, client: ClientRegistration, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self.client = ClientRegistration.model_validate(client.model_dump())
        self._transport = transport

    def __repr__(self) -> str:
        return "IndmoneyProvider(<redacted>)"

    @property
    def binding(self) -> str:
        return hashlib.sha256(self.client.private_bytes()).hexdigest()

    async def discovery(self) -> DiscoveryEvidence:
        return await discover(transport=self._transport)

    def authorization_url(self, state: str, pkce: str) -> str:
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(pkce.encode("ascii")).digest())
            .rstrip(b"=")
            .decode("ascii")
        )
        return (
            ISSUER
            + "authorize?"
            + urlencode(
                dict(
                    response_type="code",
                    client_id=self.client.client_id.get_secret_value(),
                    redirect_uri=CALLBACK,
                    scope=SCOPE,
                    state=state,
                    code_challenge=challenge,
                    code_challenge_method="S256",
                    resource=RESOURCE,
                )
            )
        )

    async def _request(self, endpoint: str, data: dict[str, str], *, revoke: bool = False) -> bytes:
        credentials = ":".join(
            quote_plus(value.get_secret_value(), safe="")
            for value in (self.client.client_id, self.client.client_secret)
        )
        headers = {
            "Authorization": "Basic "
            + base64.b64encode(credentials.encode("ascii")).decode("ascii"),
            "Accept": "application/json",
            "Accept-Encoding": "identity",
        }
        try:
            async with asyncio.timeout(10):
                async with httpx.AsyncClient(
                    transport=self._transport,
                    trust_env=False,
                    follow_redirects=False,
                    timeout=httpx.Timeout(3),
                    limits=httpx.Limits(max_connections=1, max_keepalive_connections=0),
                ) as client:
                    async with client.stream(
                        "POST", ISSUER + endpoint, data=data, headers=headers
                    ) as response:
                        for name in ("content-type", "content-encoding", "content-length"):
                            if len(response.headers.get_list(name)) > 1:
                                raise ConnectorUnavailable()
                        length = response.headers.get("content-length")
                        if length is not None and (
                            not length.isascii()
                            or not length.isdecimal()
                            or len(length) > 5
                            or int(length) > 32768
                        ):
                            raise ConnectorUnavailable()
                        if (
                            response.status_code != 200
                            or response.headers.get("content-encoding", "identity") != "identity"
                        ):
                            raise ConnectorUnavailable()
                        if (
                            not revoke
                            and response.headers.get("content-type", "")
                            .split(";", 1)[0]
                            .strip()
                            .lower()
                            != "application/json"
                        ):
                            raise ConnectorUnavailable()
                        raw = bytearray()
                        async for chunk in response.aiter_raw():
                            if len(raw) + len(chunk) > 32768:
                                raise ConnectorUnavailable()
                            raw.extend(chunk)
                        if length is not None and len(raw) != int(length):
                            raise ConnectorUnavailable()
                        return bytes(raw)
        except Exception:
            raise ConnectorUnavailable() from None

    async def exchange(self, code: SecretStr, pkce: SecretStr) -> TokenSecrets:
        raw = await self._request(
            "token",
            dict(
                grant_type="authorization_code",
                code=code.get_secret_value(),
                code_verifier=pkce.get_secret_value(),
                redirect_uri=CALLBACK,
                resource=RESOURCE,
            ),
        )
        return self._tokens(raw)

    async def refresh(self, tokens: TokenSecrets) -> TokenSecrets:
        if tokens.refresh_token is None:
            raise ConnectorUnavailable()
        raw = await self._request(
            "token",
            dict(
                grant_type="refresh_token",
                refresh_token=tokens.refresh_token.get_secret_value(),
                resource=RESOURCE,
                scope=SCOPE,
            ),
        )
        result = self._tokens(raw)
        # OAuth permits an unchanged refresh token. An uncertain response is never retried.
        if result.refresh_token is None:
            result = result.model_copy(update={"refresh_token": tokens.refresh_token})
        return result

    @staticmethod
    def _tokens(raw: bytes) -> TokenSecrets:
        try:
            return TokenSecrets.model_validate(private_document(raw))
        except ValidationError:
            raise ConnectorUnavailable() from None

    async def revoke(self, tokens: TokenSecrets) -> None:
        # Revoke both known credentials; a partial result is not confirmed cleanup.
        failed = False
        for hint, token in (
            ("refresh_token", tokens.refresh_token),
            ("access_token", tokens.access_token),
        ):
            if token is not None:
                try:
                    await self._request(
                        "revoke",
                        dict(token=token.get_secret_value(), token_type_hint=hint),
                        revoke=True,
                    )
                except ConnectorUnavailable:
                    failed = True
        if failed:
            raise ConnectorUnavailable()
