"""Server-only session values and authenticated encryption using cryptography."""

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

from trading_auth.models import AuthenticationDenied, AuthenticationUnavailable, Identity, Tokens

type Stage = Literal["login", "active", "recovery", "password", "factor"]
type Event = Literal[
    "login",
    "mfa",
    "renewal",
    "logout",
    "revoke_all",
    "recovery_request",
    "recovery_verify",
    "password_change",
    "factor_add",
    "factor_remove",
    "expiry",
]
type Outcome = Literal["success", "denied", "unavailable"]


def new_cookie() -> str:
    return secrets.token_urlsafe(32)


def verifier(cookie: str) -> bytes:
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", cookie):
        raise AuthenticationDenied()
    return hashlib.sha256(cookie.encode("ascii")).digest()


class SessionState(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    access: SecretStr = Field(repr=False, min_length=32, max_length=16384)
    refresh: SecretStr = Field(repr=False, min_length=16, max_length=4096)
    issuer: str = Field(repr=False, max_length=512)
    subject: UUID = Field(repr=False)
    provider_session: UUID = Field(repr=False)
    aal: Literal["aal1", "aal2"]
    token_expiry: int
    primary: Literal["password", "otp"] = "password"
    csrf: str = Field(pattern=r"^[0-9a-f]{64}$", repr=False)
    fresh_until: int
    factors: tuple[UUID, ...] = Field(default=(), max_length=10, repr=False)
    unverified: tuple[UUID, ...] = Field(default=(), max_length=10, repr=False)
    enrolling: UUID | None = Field(default=None, repr=False)
    proof: UUID | None = Field(default=None, repr=False)

    @classmethod
    def from_tokens(cls, tokens: Tokens, **kwargs: object) -> SessionState:
        return cls.model_validate(
            {
                "access": tokens.access,
                "refresh": tokens.refresh,
                "issuer": tokens.identity.issuer,
                "subject": tokens.identity.subject,
                "provider_session": tokens.identity.session_id,
                "aal": tokens.identity.aal,
                "token_expiry": tokens.identity.expires_at,
                **kwargs,
            }
        )

    def tokens(self) -> Tokens:
        return Tokens(
            self.access,
            self.refresh,
            Identity(
                self.issuer,
                self.subject,
                self.provider_session,
                self.aal,
                self.token_expiry,
            ),
        )

    def renewed(self, tokens: Tokens) -> SessionState:
        if (
            tokens.identity.issuer,
            tokens.identity.subject,
            tokens.identity.session_id,
            tokens.identity.aal,
        ) != (self.issuer, self.subject, self.provider_session, self.aal):
            raise AuthenticationDenied()
        return self.model_copy(
            update={
                "access": tokens.access,
                "refresh": tokens.refresh,
                "token_expiry": tokens.identity.expires_at,
            }
        )


@dataclass(frozen=True, repr=False)
class SessionRow:
    verifier: bytes
    reference: UUID
    owner: UUID
    stage: Stage
    sealed: bytes
    created: datetime
    expires: datetime
    idle: datetime
    lease: UUID


class Vault:
    def __init__(self, key: bytes) -> None:
        if len(key) != 32:
            raise AuthenticationUnavailable()
        self._cipher = AESGCM(key)
        self._rate_key = hmac.digest(key, b"admission-v1", "sha256")
        self._workspace_key = hmac.digest(key, b"workspace-context-v1", "sha256")
        self.csrf_secret = hmac.digest(key, b"csrf-v1", "sha256").hex()

    def rate_key(self, identity: str) -> bytes:
        return hmac.digest(self._rate_key, identity.casefold().encode(), "sha256")

    def workspace_context(self, key: bytes) -> str:
        """A non-authorizing view binding; never expose the cookie verifier itself."""
        if type(key) is not bytes or len(key) != 32:
            raise AuthenticationUnavailable()
        return hmac.digest(self._workspace_key, key, "sha256").hex()

    def seal(self, state: SessionState, key: bytes) -> bytes:
        import json

        values = state.model_dump(mode="json")
        values.update(
            access=state.access.get_secret_value(), refresh=state.refresh.get_secret_value()
        )
        nonce = secrets.token_bytes(12)
        return nonce + self._cipher.encrypt(
            nonce, json.dumps(values).encode(), b"session-v1:" + key
        )

    def open(self, row: SessionRow) -> SessionState:
        try:
            raw = self._cipher.decrypt(
                row.sealed[:12], row.sealed[12:], b"session-v1:" + row.verifier
            )
            return SessionState.model_validate_json(raw)
        except InvalidTag, ValueError, ValidationError:
            raise AuthenticationUnavailable() from None
