"""Validated, redacted values for a future server-side OIDC authorization flow.

These values are configuration or unverified protocol inputs, never authentication
results. Constructing an identity anchor does not establish who controls it.
"""

import re
from dataclasses import dataclass
from ipaddress import IPv4Address
from urllib.parse import SplitResult, urlsplit

from pydantic import SecretStr

from trading_auth.models import AuthenticationDenied, AuthenticationUnavailable

ATTEMPT_VERSION = 1
ATTEMPT_SECONDS = 300
MAX_AUTHENTICATION_AGE = 300
MAX_TIMESTAMP = 253402300799


def _https_url(value: str) -> SplitResult:
    if type(value) is not str or not 1 <= len(value) <= 512:
        raise ValueError()
    # Reject characters urlsplit would discard/normalize, encoded path ambiguity,
    # credentials, and user-selected query/fragment additions before parsing.
    if re.fullmatch(r"[\x21-\x7e]+", value, re.ASCII) is None or any(
        character in value for character in ("\\", "%", "?", "#")
    ):
        raise ValueError()
    target = urlsplit(value)
    host = target.hostname
    if (
        target.scheme != "https"
        or not value.startswith("https://")
        or not host
        or target.username is not None
        or target.password is not None
        or target.netloc != target.netloc.lower()
        or target.netloc.endswith(":")
        or target.port == 0
        or re.fullmatch(r"[a-z0-9]+(?:[a-z0-9.-]*[a-z0-9])?", host, re.ASCII) is None
        or any(
            not label or len(label) > 63 or label.startswith("-") or label.endswith("-")
            for label in host.split(".")
        )
        or len(host) > 253
        or re.fullmatch(r"(?:/[A-Za-z0-9._~-]*)*", target.path, re.ASCII) is None
        or "//" in target.path
        or any(segment in {".", ".."} for segment in target.path.split("/"))
    ):
        raise ValueError()
    # This first contract supports canonical DNS/IPv4 authorities only. Do not
    # silently normalize leading-zero ports, IPv6 authorities, or host casing.
    if re.fullmatch(r"[0-9.]+", host, re.ASCII) is not None:
        if str(IPv4Address(host)) != host:
            raise ValueError()
    authority = host + (f":{target.port}" if target.port is not None else "")
    if target.netloc != authority:
        raise ValueError()
    return target


def _secret(value: SecretStr) -> str:
    if type(value) is not SecretStr:
        raise ValueError()
    raw = value.get_secret_value()
    if re.fullmatch(r"[A-Za-z0-9_-]{43}", raw, re.ASCII) is None:
        raise ValueError()
    return raw


def _timestamp(value: int) -> None:
    if type(value) is not int or not 0 <= value <= MAX_TIMESTAMP:
        raise ValueError()


@dataclass(frozen=True, repr=False)
class OidcClient:
    """Explicit operator configuration; no discovery, credentials or I/O."""

    issuer: str
    client_id: str
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str
    redirect_uri: str

    def __post_init__(self) -> None:
        try:
            issuer = _https_url(self.issuer)
            endpoints = (self.authorization_endpoint, self.token_endpoint, self.jwks_uri)
            for endpoint in endpoints:
                target = _https_url(endpoint)
                if target.netloc != issuer.netloc or not target.path:
                    raise ValueError()
            callback = _https_url(self.redirect_uri)
            if (
                not callback.path
                or len(set(endpoints)) != len(endpoints)
                or type(self.client_id) is not str
                or re.fullmatch(r"[\x21-\x7e]{1,256}", self.client_id, re.ASCII) is None
            ):
                raise ValueError()
        except ValueError, TypeError:
            raise AuthenticationUnavailable() from None


@dataclass(frozen=True, repr=False)
class IdentityAnchor:
    """An unverified exact identity address, not proof or an owner binding."""

    issuer: str
    subject: str

    def __post_init__(self) -> None:
        try:
            _https_url(self.issuer)
            if (
                type(self.subject) is not str
                or re.fullmatch(r"[\x20-\x7e]{1,255}", self.subject, re.ASCII) is None
                or self.subject != self.subject.strip()
            ):
                raise ValueError()
        except ValueError, TypeError:
            raise AuthenticationDenied() from None


@dataclass(frozen=True, repr=False)
class LoginAttempt:
    """Server-only attempt values; persistence and single-use claims are separate."""

    client: OidcClient
    state: SecretStr
    nonce: SecretStr
    pkce_verifier: SecretStr
    browser_binding: SecretStr
    admitted_at: int
    expires_at: int
    max_age: int
    version: int = ATTEMPT_VERSION

    def __post_init__(self) -> None:
        try:
            if type(self.client) is not OidcClient:
                raise ValueError()
            private = (self.state, self.nonce, self.pkce_verifier, self.browser_binding)
            if len({_secret(value) for value in private}) != len(private):
                raise ValueError()
            _timestamp(self.admitted_at)
            _timestamp(self.expires_at)
            if (
                type(self.version) is not int
                or self.version != ATTEMPT_VERSION
                or self.expires_at != self.admitted_at + ATTEMPT_SECONDS
                or type(self.max_age) is not int
                or not 0 <= self.max_age <= MAX_AUTHENTICATION_AGE
            ):
                raise ValueError()
        except ValueError, TypeError:
            raise AuthenticationDenied() from None

    def require_live(self, now: int) -> None:
        try:
            _timestamp(now)
            if not self.admitted_at <= now < self.expires_at:
                raise ValueError()
        except ValueError, TypeError:
            raise AuthenticationDenied() from None
