"""Private INDmoney authorization values; no financial or trading capability."""

import json
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

CALLBACK = "https://127.0.0.1:8443/api/v1/connections/indmoney/callback"
PREFIX = "/api/v1/connections/indmoney"
SCOPE = "portfolio:read"


class ConnectorUnavailable(RuntimeError):
    def __init__(self) -> None:
        super().__init__("Connection unavailable.")


class ConnectorRejected(RuntimeError):
    def __init__(self) -> None:
        super().__init__("Connection request rejected.")


class ConnectorBusy(RuntimeError):
    def __init__(self) -> None:
        super().__init__("Connection operation already pending or rate limited.")


class PrivateModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, hide_input_in_errors=True)

    def private_bytes(self) -> bytes:
        values = self.model_dump(mode="json", warnings=False)
        for key in type(self).model_fields:
            value = getattr(self, key)
            if isinstance(value, SecretStr):
                values[key] = value.get_secret_value()
        return json.dumps(values, separators=(",", ":"), allow_nan=False).encode()


class ClientRegistration(PrivateModel):
    client_id: SecretStr = Field(repr=False, min_length=1, max_length=256)
    client_secret: SecretStr = Field(repr=False, min_length=16, max_length=4096)
    callback: Literal["https://127.0.0.1:8443/api/v1/connections/indmoney/callback"] = (
        "https://127.0.0.1:8443/api/v1/connections/indmoney/callback"
    )
    issuer: Literal["https://mcp.indmoney.com/"] = "https://mcp.indmoney.com/"
    resource: Literal["https://mcp.indmoney.com/mcp"] = "https://mcp.indmoney.com/mcp"
    scope: Literal["portfolio:read"] = "portfolio:read"
    auth_method: Literal["client_secret_basic"] = "client_secret_basic"

    @field_validator("client_id", "client_secret")
    @classmethod
    def printable(cls, value: SecretStr) -> SecretStr:
        if re.fullmatch(r"[\x21-\x7e]+", value.get_secret_value(), re.ASCII) is None:
            raise ValueError("Invalid client configuration.")
        return value


class AttemptSecrets(PrivateModel):
    pkce: SecretStr = Field(repr=False, min_length=43, max_length=43)
    code: SecretStr | None = Field(default=None, repr=False, min_length=1, max_length=2048)
    issuer_required: bool
    refresh_supported: bool
    client_binding: str = Field(pattern=r"^[0-9a-f]{64}$", repr=False)


class TokenSecrets(PrivateModel):
    access_token: SecretStr = Field(repr=False, min_length=16, max_length=16384)
    refresh_token: SecretStr | None = Field(
        default=None, repr=False, min_length=16, max_length=4096
    )
    token_type: Literal["Bearer", "bearer"]
    expires_in: int = Field(ge=1, le=86400)
    scope: Literal["portfolio:read"]
    issuer: Literal["https://mcp.indmoney.com/"] = "https://mcp.indmoney.com/"
    resource: Literal["https://mcp.indmoney.com/mcp"] = "https://mcp.indmoney.com/mcp"

    @field_validator("access_token", "refresh_token")
    @classmethod
    def printable(cls, value: SecretStr | None) -> SecretStr | None:
        if (
            value is not None
            and re.fullmatch(r"[\x21-\x7e]+", value.get_secret_value(), re.ASCII) is None
        ):
            raise ValueError("Invalid token response.")
        return value


def private_document(raw: bytes) -> dict[str, Any]:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        if len(pairs) > 12 or len(dict(pairs)) != len(pairs):
            raise ValueError()
        return dict(pairs)

    def reject(_: str) -> None:
        raise ValueError()

    try:
        if not 1 <= len(raw) <= 32768:
            raise ValueError()
        value = json.loads(
            raw.decode("utf-8"), object_pairs_hook=unique, parse_constant=reject, parse_float=reject
        )
        if type(value) is not dict or any(
            type(v) not in (str, int, bool, type(None)) for v in value.values()
        ):
            raise ValueError()
        return value
    except ValueError, UnicodeError, RecursionError:
        raise ConnectorUnavailable() from None
