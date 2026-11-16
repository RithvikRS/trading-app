"""Bounded query parsing and attempt correlation; no token or identity verification."""

import re
import secrets
from dataclasses import dataclass
from urllib.parse import parse_qsl

from pydantic import SecretStr

from trading_auth.models import AuthenticationDenied
from trading_oidc.contracts import LoginAttempt, _https_url, _secret


@dataclass(frozen=True, repr=False)
class ParsedCallback:
    """Untrusted parsed protocol values. A missing code is provider denial."""

    state: SecretStr
    issuer: str
    code: SecretStr | None

    def __post_init__(self) -> None:
        try:
            _secret(self.state)
            _https_url(self.issuer)
            if self.code is not None and (
                type(self.code) is not SecretStr
                or re.fullmatch(r"[\x21-\x7e]{1,2048}", self.code.get_secret_value(), re.ASCII)
                is None
            ):
                raise ValueError()
        except ValueError, TypeError:
            raise AuthenticationDenied() from None


def parse_callback(raw_query: bytes) -> ParsedCallback:
    """Parse the selected GET/code/RFC9207 profile without admitting a request.

    The eventual HTTP route must independently check method, origin/host,
    duplicate headers/cookies, navigation shape and empty body. No raw errors,
    error descriptions, error URLs or unknown fields escape this parser.
    """
    try:
        if type(raw_query) is not bytes or not 1 <= len(raw_query) <= 8192:
            raise ValueError()
        query = raw_query.decode("ascii")
        if re.search(r"%(?![0-9A-Fa-f]{2})", query):
            raise ValueError()
        pairs = parse_qsl(
            query,
            keep_blank_values=True,
            strict_parsing=True,
            encoding="utf-8",
            errors="strict",
            max_num_fields=6,
        )
        values = dict(pairs)
        if (
            len(values) != len(pairs)
            or not {"state", "iss"} <= values.keys()
            or not values.keys()
            <= {"state", "iss", "code", "error", "error_description", "error_uri"}
            or ("code" in values) == ("error" in values)
            or any(
                re.fullmatch(r"[\x20-\x7e]{1,2048}", value, re.ASCII) is None
                for value in values.values()
            )
            or ("code" in values and bool({"error_description", "error_uri"} & values.keys()))
            or (
                "error" in values
                and re.fullmatch(r"[a-z][a-z0-9_]{0,63}", values["error"], re.ASCII) is None
            )
        ):
            raise ValueError()
        return ParsedCallback(
            SecretStr(values["state"]),
            values["iss"],
            SecretStr(values["code"]) if "code" in values else None,
        )
    except ValueError, TypeError, UnicodeError:
        raise AuthenticationDenied() from None


def check_callback_binding(
    attempt: LoginAttempt,
    callback: ParsedCallback,
    browser_binding: SecretStr,
    now: int,
) -> None:
    """Check correlation only; this does NOT consume state or authenticate.

    Durable storage must atomically claim the still-live attempt before token
    exchange. Repeated calls to this pure helper deliberately cannot establish
    single-use/replay guarantees. An uncertain exchange must not restore a claim.
    """
    try:
        if type(attempt) is not LoginAttempt or type(callback) is not ParsedCallback:
            raise ValueError()
        attempt.require_live(now)
        binding = _secret(browser_binding)
        if (
            not secrets.compare_digest(
                attempt.state.get_secret_value(), callback.state.get_secret_value()
            )
            or not secrets.compare_digest(attempt.browser_binding.get_secret_value(), binding)
            or callback.issuer != attempt.client.issuer
        ):
            raise ValueError()
    except ValueError, TypeError:
        raise AuthenticationDenied() from None
