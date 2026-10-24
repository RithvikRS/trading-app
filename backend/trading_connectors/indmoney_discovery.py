"""Credential-free validation of INDmoney's advertised OAuth capabilities."""

import asyncio
import json
from dataclasses import dataclass
from typing import Any, NoReturn

import httpx2 as httpx

RESOURCE = "https://mcp.indmoney.com/mcp"
ISSUER = "https://mcp.indmoney.com/"
RESOURCE_METADATA = ISSUER + ".well-known/oauth-protected-resource/mcp"
SERVER_METADATA = ISSUER + ".well-known/oauth-authorization-server"
MAX_DOCUMENT_BYTES = 16384
DISCOVERY_SECONDS = 10


class DiscoveryUnavailable(RuntimeError):
    def __init__(self) -> None:
        super().__init__("INDmoney discovery is unavailable or incompatible.")


@dataclass(frozen=True)
class DiscoveryEvidence:
    """An advertisement only: never proof of enrollment, consent or account access."""

    refresh_advertised: bool
    registration_advertised: bool
    response_issuer_advertised: bool


def _reject_number(_: str) -> NoReturn:
    raise DiscoveryUnavailable()


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    if len(pairs) > 24:
        raise DiscoveryUnavailable()
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DiscoveryUnavailable()
        result[key] = value
    return result


def _document(raw: bytes) -> dict[str, Any]:
    if type(raw) is not bytes or not 1 <= len(raw) <= MAX_DOCUMENT_BYTES:
        raise DiscoveryUnavailable()
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_pairs,
            parse_int=_reject_number,
            parse_float=_reject_number,
            parse_constant=_reject_number,
        )
    except UnicodeError, ValueError, RecursionError:
        raise DiscoveryUnavailable() from None
    if not isinstance(value, dict):
        raise DiscoveryUnavailable()
    return value


def _choices(value: Any, allowed: set[str], required: set[str]) -> set[str]:
    if (
        not isinstance(value, list)
        or not value
        or len(value) > len(allowed)
        or any(type(item) is not str for item in value)
    ):
        raise DiscoveryUnavailable()
    selected = set(value)
    if len(selected) != len(value) or not required <= selected <= allowed:
        raise DiscoveryUnavailable()
    return selected


def validate_metadata(resource_raw: bytes, server_raw: bytes) -> DiscoveryEvidence:
    """Validate a deliberately narrow provider contract, not arbitrary OAuth discovery."""
    resource, server = _document(resource_raw), _document(server_raw)
    if resource != {
        "resource": RESOURCE,
        "authorization_servers": [ISSUER],
        "scopes_supported": ["portfolio:read"],
        "bearer_methods_supported": ["header"],
    }:
        raise DiscoveryUnavailable()
    endpoints = {
        "issuer": ISSUER,
        "authorization_endpoint": ISSUER + "authorize",
        "token_endpoint": ISSUER + "token",
        "revocation_endpoint": ISSUER + "revoke",
        "service_documentation": "https://www.indmoney.com/mcp",
    }
    lists = {
        "scopes_supported",
        "response_types_supported",
        "grant_types_supported",
        "token_endpoint_auth_methods_supported",
        "revocation_endpoint_auth_methods_supported",
        "code_challenge_methods_supported",
    }
    optional = {"registration_endpoint", "authorization_response_iss_parameter_supported"}
    required = set(endpoints) | lists
    if not required <= set(server) <= required | optional:
        raise DiscoveryUnavailable()
    if any(server[key] != value for key, value in endpoints.items()):
        raise DiscoveryUnavailable()
    registration = "registration_endpoint" in server
    if registration and server["registration_endpoint"] != ISSUER + "register":
        raise DiscoveryUnavailable()
    response_issuer = server.get("authorization_response_iss_parameter_supported", False)
    if type(response_issuer) is not bool:
        raise DiscoveryUnavailable()
    _choices(server["scopes_supported"], {"portfolio:read", "market:read"}, {"portfolio:read"})
    _choices(server["response_types_supported"], {"code"}, {"code"})
    grants = _choices(
        server["grant_types_supported"],
        {"authorization_code", "refresh_token"},
        {"authorization_code"},
    )
    _choices(server["code_challenge_methods_supported"], {"S256"}, {"S256"})
    for key in (
        "token_endpoint_auth_methods_supported",
        "revocation_endpoint_auth_methods_supported",
    ):
        _choices(server[key], {"client_secret_basic", "client_secret_post"}, set())
    return DiscoveryEvidence("refresh_token" in grants, registration, response_issuer)


async def _read(client: httpx.AsyncClient, url: str) -> bytes:
    # Only the two constants below reach this private function. The public API accepts no URL.
    client.cookies.clear()
    async with client.stream(
        "GET", url, headers={"Accept": "application/json", "Accept-Encoding": "identity"}
    ) as response:
        content_types = response.headers.get_list("content-type")
        encodings = response.headers.get_list("content-encoding")
        lengths = response.headers.get_list("content-length")
        if (
            response.status_code != 200
            or len(content_types) != 1
            or content_types[0].split(";", 1)[0].strip().lower() != "application/json"
            or encodings not in ([], ["identity"])
            or len(lengths) > 1
            or (
                lengths
                and (
                    not lengths[0].isascii()
                    or not lengths[0].isdecimal()
                    or len(lengths[0]) > 5
                    or not 1 <= int(lengths[0]) <= MAX_DOCUMENT_BYTES
                )
            )
        ):
            raise DiscoveryUnavailable()
        data = bytearray()
        async for chunk in response.aiter_raw(chunk_size=4096):
            if len(data) + len(chunk) > MAX_DOCUMENT_BYTES:
                raise DiscoveryUnavailable()
            data.extend(chunk)
        if lengths and len(data) != int(lengths[0]):
            raise DiscoveryUnavailable()
        return bytes(data)


async def discover(*, transport: httpx.AsyncBaseTransport | None = None) -> DiscoveryEvidence:
    """Read public metadata only. Transport injection is a local test seam, not configuration."""
    try:
        async with asyncio.timeout(DISCOVERY_SECONDS):
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(3, connect=3, pool=1),
                limits=httpx.Limits(max_connections=1, max_keepalive_connections=0),
                follow_redirects=False,
                trust_env=False,
                verify=True,
                transport=transport,
            ) as client:
                resource = await _read(client, RESOURCE_METADATA)
                server = await _read(client, SERVER_METADATA)
                return validate_metadata(resource, server)
    except httpx.HTTPError, TimeoutError, OSError, ValueError, RecursionError:
        raise DiscoveryUnavailable() from None
