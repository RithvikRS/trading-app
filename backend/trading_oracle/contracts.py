"""Closed local-only values for the synthetic Oracle ownership baseline."""

import re
import secrets
import unicodedata
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

Role = Literal["TRADING_MIGRATOR", "TRADING_RUNTIME", "TRADING_AUTH"]
ROLES: tuple[Role, ...] = ("TRADING_MIGRATOR", "TRADING_RUNTIME", "TRADING_AUTH")
MAX_REVISION = 9007199254740991


class OracleUnavailable(RuntimeError):
    def __init__(self) -> None:
        super().__init__("Oracle baseline is unavailable.")


class OracleMigrationInterrupted(OracleUnavailable):
    """A known committing step needs explicit reconciliation before another install."""


class OracleOwnerDenied(PermissionError):
    def __init__(self) -> None:
        super().__init__("Workspace access denied.")


class LocalTarget(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, hide_input_in_errors=True)
    run_id: str = Field(pattern=r"^[0-9a-f]{32}$", repr=False)
    port: int = Field(ge=1024, le=65535)
    version: Literal[1] = 1

    @field_validator("version", mode="before")
    @classmethod
    def exact_version(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("Invalid local target version.")
        return value


class RoleSecrets(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, hide_input_in_errors=True)
    migrator: SecretStr = Field(repr=False)
    runtime: SecretStr = Field(repr=False)
    auth: SecretStr = Field(repr=False)

    @field_validator("migrator", "runtime", "auth")
    @classmethod
    def closed_password(cls, value: SecretStr) -> SecretStr:
        if re.fullmatch(r"Ta1[0-9a-f]{48}", value.get_secret_value()) is None:
            raise ValueError("Invalid synthetic credential.")
        return value

    def for_role(self, role: Role) -> SecretStr:
        if role == "TRADING_MIGRATOR":
            return self.migrator
        if role == "TRADING_RUNTIME":
            return self.runtime
        if role == "TRADING_AUTH":
            return self.auth
        raise OracleUnavailable()


def new_role_secrets() -> RoleSecrets:
    return RoleSecrets(
        migrator=SecretStr("Ta1" + secrets.token_hex(24)),
        runtime=SecretStr("Ta1" + secrets.token_hex(24)),
        auth=SecretStr("Ta1" + secrets.token_hex(24)),
    )


class IdentityKey(BaseModel):
    """Preserve exact UTF-8 spelling; authentication verifies the provider separately."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, hide_input_in_errors=True)
    issuer: str = Field(repr=False)
    subject: str = Field(repr=False)

    @field_validator("issuer", "subject")
    @classmethod
    def plain_exact_text(cls, value: str) -> str:
        if (
            not value
            or value != value.strip()
            or any(unicodedata.category(character).startswith("C") for character in value)
        ):
            raise ValueError("Invalid exact identity.")
        return value

    @field_validator("issuer")
    @classmethod
    def issuer_bytes(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 512:
            raise ValueError("Invalid exact identity.")
        return value

    @field_validator("subject")
    @classmethod
    def subject_bytes(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 256:
            raise ValueError("Invalid exact identity.")
        return value


def owner_bytes(value: UUID) -> bytes:
    if type(value) is not UUID or value.int == 0:
        raise OracleOwnerDenied()
    return value.bytes


def exact_uuid(value: object) -> UUID:
    if type(value) is not bytes or len(value) != 16 or not any(value):
        raise OracleUnavailable()
    return UUID(bytes=value)
