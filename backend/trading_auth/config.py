"""Only an explicitly configured HTTPS Supabase project and publishable API key."""

import os
import re
from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, SecretStr, ValidationError, model_validator

from trading_auth.models import AuthenticationUnavailable


class AuthSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, hide_input_in_errors=True)
    project_url: str
    publishable_key: SecretStr
    recovery_email_enabled: bool = False

    @model_validator(mode="after")
    def validate_target(self) -> AuthSettings:
        if not re.fullmatch(r"https://[a-z0-9]{20}\.supabase\.co", self.project_url):
            raise ValueError("A canonical Supabase project URL is required.")
        if not re.fullmatch(
            r"sb_publishable_[A-Za-z0-9_-]{20,200}", self.publishable_key.get_secret_value()
        ):
            raise ValueError("Only a publishable key is accepted.")
        return self

    @property
    def issuer(self) -> str:
        return self.project_url + "/auth/v1"


def load_settings(environ: Mapping[str, str] | None = None) -> AuthSettings:
    source = os.environ if environ is None else environ
    allowed = {
        "TRADING_AUTH_PROJECT_URL",
        "TRADING_AUTH_PUBLISHABLE_KEY",
        "TRADING_AUTH_RECOVERY_EMAIL_ENABLED",
    }
    if {key for key in source if key.upper().startswith("TRADING_AUTH_")} - allowed:
        raise AuthenticationUnavailable()
    try:
        recovery = source.get("TRADING_AUTH_RECOVERY_EMAIL_ENABLED", "false")
        if recovery not in {"true", "false"}:
            raise AuthenticationUnavailable()
        return AuthSettings(
            project_url=source["TRADING_AUTH_PROJECT_URL"],
            publishable_key=SecretStr(source["TRADING_AUTH_PUBLISHABLE_KEY"]),
            recovery_email_enabled=recovery == "true",
        )
    except KeyError, ValidationError:
        raise AuthenticationUnavailable() from None
