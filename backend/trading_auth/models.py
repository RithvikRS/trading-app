"""Small immutable contracts with redacted representations for sensitive values."""

from dataclasses import dataclass, field
from typing import Literal, Protocol
from uuid import UUID

from pydantic import SecretStr


class AuthenticationDenied(ValueError):
    def __init__(self) -> None:
        super().__init__("Authentication could not be completed.")


class AuthenticationUnavailable(RuntimeError):
    def __init__(self) -> None:
        super().__init__("Authentication is temporarily unavailable.")


class WorkspaceContextChanged(ValueError):
    def __init__(self) -> None:
        super().__init__("The workspace sign-in context changed.")


class AuthenticationLimited(AuthenticationDenied):
    pass


@dataclass(frozen=True, repr=False)
class Identity:
    issuer: str
    subject: UUID
    session_id: UUID
    aal: Literal["aal1", "aal2"]
    expires_at: int


@dataclass(frozen=True, repr=False)
class Tokens:
    access: SecretStr
    refresh: SecretStr
    identity: Identity


@dataclass(frozen=True, repr=False)
class Factor:
    id: UUID
    kind: str
    verified: bool


@dataclass(frozen=True, repr=False)
class Enrollment:
    factor_id: UUID
    # Never render provider SVG or follow a provider-supplied link. The future UI
    # can encode this validated secret with its own QR component.
    secret: SecretStr


@dataclass(frozen=True, repr=False)
class OwnerBinding:
    owner_id: UUID
    mfa_enrolled: bool


@dataclass(frozen=True)
class AuthenticatedOwner:
    """Internal result only; this is neither a browser session nor a bearer token."""

    owner_id: UUID = field(repr=False)
    identity: Identity = field(repr=False)


class IdentityStore(Protocol):
    def lookup(self, issuer: str, subject: UUID) -> OwnerBinding | None: ...

    def complete_enrollment(self, issuer: str, subject: UUID, owner_id: UUID) -> None: ...


class Provider(Protocol):
    def password(self, email: str, password: SecretStr) -> Tokens: ...

    def factors(self, tokens: Tokens) -> tuple[Factor, ...]: ...

    def enroll(self, tokens: Tokens) -> Enrollment: ...

    def verify(self, tokens: Tokens, factor: UUID, code: SecretStr) -> Tokens: ...

    def discard(self, tokens: Tokens) -> None: ...
