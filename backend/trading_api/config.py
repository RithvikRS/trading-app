"""Explicit environment configuration without implicit files or secret discovery."""

import os
from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

PREFIX = "TRADING_API_"
ALLOWED_KEYS = frozenset({f"{PREFIX}ENVIRONMENT", f"{PREFIX}PORT", f"{PREFIX}AUTH_ENABLED"})


class ConfigurationError(ValueError):
    """A configuration failure whose message never contains supplied values."""


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, hide_input_in_errors=True)

    # Hosted modes remain unavailable until the corresponding controls exist.
    environment: Literal["development", "test"] = "development"
    port: int = Field(default=8000, ge=1024, le=65535)
    auth_enabled: bool = False


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
        if auth not in {"true", "false"}:
            raise ConfigurationError("Invalid API configuration; see docs/development.md.")
        return Settings.model_validate(
            {
                "environment": source.get(f"{PREFIX}ENVIRONMENT", "development"),
                "port": int(port),
                "auth_enabled": auth == "true",
            }
        )
    except ValidationError:
        raise ConfigurationError("Invalid API configuration; see docs/development.md.") from None
