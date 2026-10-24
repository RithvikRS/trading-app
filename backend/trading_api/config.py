"""Explicit environment configuration without implicit files or secret discovery."""

import os
from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

PREFIX = "TRADING_API_"
ALLOWED_KEYS = frozenset(
    {
        f"{PREFIX}ENVIRONMENT",
        f"{PREFIX}PORT",
        f"{PREFIX}AUTH_ENABLED",
        f"{PREFIX}FRONTEND_ENABLED",
        f"{PREFIX}HTTPS_ENABLED",
        f"{PREFIX}INDMONEY_ENABLED",
    }
)


class ConfigurationError(ValueError):
    """A configuration failure whose message never contains supplied values."""


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, hide_input_in_errors=True)

    # Hosted modes remain unavailable until the corresponding controls exist.
    environment: Literal["development", "test"] = "development"
    port: int = Field(default=8000, ge=1024, le=65535)
    auth_enabled: bool = False
    frontend_enabled: bool = False
    https_enabled: bool = False
    indmoney_enabled: bool = False

    @model_validator(mode="after")
    def connector_transport(self) -> Settings:
        if self.https_enabled and self.port != 8443:
            raise ValueError("Local HTTPS requires the registered origin.")
        if self.indmoney_enabled and not (self.auth_enabled and self.https_enabled):
            raise ValueError("INDmoney requires authenticated HTTPS.")
        return self


def load_settings(environ: Mapping[str, str] | None = None) -> Settings:
    source = os.environ if environ is None else environ
    keys = {key for key in source if key.upper().startswith(PREFIX)}
    if keys - ALLOWED_KEYS:
        raise ConfigurationError("Invalid API configuration; see docs/development.md.")

    port = source.get(f"{PREFIX}PORT", "8000")
    if not port.isascii() or not port.isdecimal() or not 4 <= len(port) <= 5:
        raise ConfigurationError("Invalid API configuration; see docs/development.md.")
    if port.startswith("0"):
        raise ConfigurationError("Invalid API configuration; see docs/development.md.")

    try:
        auth = source.get(f"{PREFIX}AUTH_ENABLED", "false")
        frontend = source.get(f"{PREFIX}FRONTEND_ENABLED", "false")
        https = source.get(f"{PREFIX}HTTPS_ENABLED", "false")
        indmoney = source.get(f"{PREFIX}INDMONEY_ENABLED", "false")
        if any(value not in {"true", "false"} for value in (auth, frontend, https, indmoney)):
            raise ConfigurationError("Invalid API configuration; see docs/development.md.")
        return Settings.model_validate(
            {
                "environment": source.get(f"{PREFIX}ENVIRONMENT", "development"),
                "port": int(port),
                "auth_enabled": auth == "true",
                "frontend_enabled": frontend == "true",
                "https_enabled": https == "true",
                "indmoney_enabled": indmoney == "true",
            }
        )
    except ValidationError:
        raise ConfigurationError("Invalid API configuration; see docs/development.md.") from None
