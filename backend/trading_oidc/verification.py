"""Offline verification of a deliberately narrow OIDC ID-token profile.

Trusted JWKS bytes are supplied by the caller. This module performs no discovery,
network access, owner resolution, attempt consumption or session creation.
"""

import base64
import json
import re
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol, cast

from authlib.oidc.core import CodeIDToken  # type: ignore[import-untyped]
from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import RSAKey
from pydantic import SecretStr

from trading_auth.models import AuthenticationDenied, AuthenticationUnavailable
from trading_oidc.contracts import MAX_TIMESTAMP, IdentityAnchor, LoginAttempt

CLOCK_SKEW_SECONDS = 30
MAX_TOKEN_SECONDS = 3600
MAX_TOKEN_BYTES = 16384
MAX_JWKS_BYTES = 65536
MAX_KEYS = 8
_REQUIRED_AMR = frozenset({"pwd", "otp", "mfa"})


class VerifiedTokenEvidence(Protocol):
    """Verifier output only; it grants neither owner access nor a browser session."""

    @property
    def identity(self) -> IdentityAnchor: ...

    @property
    def audience(self) -> str: ...

    @property
    def issued_at(self) -> int: ...

    @property
    def expires_at(self) -> int: ...

    @property
    def authenticated_at(self) -> int: ...

    @property
    def amr(self) -> tuple[str, ...]: ...


@dataclass(frozen=True, repr=False)
class _VerifiedTokenEvidence:
    identity: IdentityAnchor
    audience: str
    issued_at: int
    expires_at: int
    authenticated_at: int
    amr: tuple[str, ...]


class _ClaimValidator(Protocol):
    def validate(self, now: int, leeway: int) -> None: ...


# Authlib does not ship a py.typed marker. Keep its untyped API behind this
# explicit, tested adapter; JOSE signature verification uses typed joserfc.
_claim_validator = cast(
    Callable[[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]], _ClaimValidator],
    CodeIDToken,
)


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for key, value in pairs:
        if key in values:
            raise ValueError()
        values[key] = value
    return values


def _no_fraction_or_constant(value: str) -> None:
    raise ValueError()


class _StrictDecoder(json.JSONDecoder):
    def __init__(self, **kwargs: Any) -> None:
        kwargs.update(
            object_pairs_hook=_pairs,
            parse_float=_no_fraction_or_constant,
            parse_constant=_no_fraction_or_constant,
        )
        super().__init__(**kwargs)


def _object(raw: bytes, maximum: int) -> dict[str, Any]:
    if type(raw) is not bytes or not 1 <= len(raw) <= maximum:
        raise ValueError()
    decoded = json.loads(raw.decode("utf-8"), cls=_StrictDecoder)
    if type(decoded) is not dict:
        raise ValueError()
    pending = [(decoded, 0)]
    while pending:
        value, depth = pending.pop()
        if depth > 4:
            raise ValueError()
        if isinstance(value, dict):
            if len(value) > 16:
                raise ValueError()
            pending.extend((child, depth + 1) for child in value.values())
        elif isinstance(value, list):
            if len(value) > 16:
                raise ValueError()
            pending.extend((child, depth + 1) for child in value)
    return cast(dict[str, Any], decoded)


def _base64url(value: str, maximum: int) -> bytes:
    if (
        type(value) is not str
        or not 1 <= len(value) <= maximum
        or re.fullmatch(r"[A-Za-z0-9_-]+", value, re.ASCII) is None
    ):
        raise ValueError()
    raw = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    if base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii") != value:
        raise ValueError()
    return raw


def _kid(value: object) -> str:
    if type(value) is not str or re.fullmatch(r"[A-Za-z0-9._~-]{1,128}", value, re.ASCII) is None:
        raise ValueError()
    return value


def _keys(raw: bytes) -> dict[str, tuple[RSAKey, int]]:
    try:
        document = _object(raw, MAX_JWKS_BYTES)
        values = document.get("keys")
        if (
            document.keys() != {"keys"}
            or type(values) is not list
            or not 1 <= len(values) <= MAX_KEYS
        ):
            raise ValueError()
        result: dict[str, tuple[RSAKey, int]] = {}
        for value in values:
            if (
                type(value) is not dict
                or not {"kty", "kid", "n", "e"} <= value.keys()
                or not value.keys() <= {"kty", "kid", "n", "e", "alg", "use", "key_ops"}
                or value["kty"] != "RSA"
                or value.get("alg", "RS256") != "RS256"
                or value.get("use", "sig") != "sig"
                or value.get("key_ops", ["verify"]) != ["verify"]
                or value["e"] != "AQAB"
            ):
                raise ValueError()
            key_id = _kid(value["kid"])
            modulus = _base64url(value["n"], 684)
            integer = int.from_bytes(modulus)
            if (
                key_id in result
                or not modulus
                or modulus[0] == 0
                or integer.bit_length() not in {2048, 3072, 4096}
                or integer % 2 != 1
            ):
                raise ValueError()
            key = RSAKey.import_key(cast(dict[str, str | list[str]], value))
            result[key_id] = (key, len(modulus))
        return result
    except ValueError, TypeError, KeyError, RecursionError, JoseError:
        raise AuthenticationUnavailable() from None


def _integer(claims: dict[str, Any], name: str) -> int:
    value = claims.get(name)
    if type(value) is not int or not 0 <= value <= MAX_TIMESTAMP:
        raise ValueError()
    return value


def _claims(
    values: dict[str, Any],
    attempt: LoginAttempt,
    now: int,
    access_token: SecretStr | None,
) -> tuple[IdentityAnchor, int, int, int, tuple[str, ...], str | None]:
    required = {"iss", "sub", "aud", "exp", "iat", "auth_time", "nonce", "amr"}
    if not required <= values.keys() or not values.keys() <= required | {"azp", "nbf", "at_hash"}:
        raise ValueError()
    if type(values["iss"]) is not str or values["iss"] != attempt.client.issuer:
        raise ValueError()
    identity = IdentityAnchor(values["iss"], values["sub"])
    audience = values["aud"]
    if type(audience) is list:
        if len(audience) != 1:
            raise ValueError()
        audience = audience[0]
    if type(audience) is not str or audience != attempt.client.client_id:
        raise ValueError()
    if "azp" in values and (
        type(values["azp"]) is not str or values["azp"] != attempt.client.client_id
    ):
        raise ValueError()
    nonce = values["nonce"]
    if (
        type(nonce) is not str
        or re.fullmatch(r"[A-Za-z0-9_-]{43}", nonce, re.ASCII) is None
        or not secrets.compare_digest(nonce, attempt.nonce.get_secret_value())
    ):
        raise ValueError()
    issued, expires, authenticated = (
        _integer(values, name) for name in ("iat", "exp", "auth_time")
    )
    if (
        not authenticated <= issued < expires
        or expires <= now
        or expires - issued > MAX_TOKEN_SECONDS
        or issued < attempt.admitted_at - CLOCK_SKEW_SECONDS
        or issued > now + CLOCK_SKEW_SECONDS
        or authenticated > now + CLOCK_SKEW_SECONDS
        or now - authenticated > attempt.max_age + CLOCK_SKEW_SECONDS
    ):
        raise ValueError()
    if "nbf" in values:
        not_before = _integer(values, "nbf")
        if not_before >= expires or not_before > now + CLOCK_SKEW_SECONDS:
            raise ValueError()
    methods = values["amr"]
    if (
        type(methods) is not list
        or len(methods) != len(_REQUIRED_AMR)
        or any(type(method) is not str for method in methods)
        or frozenset(methods) != _REQUIRED_AMR
    ):
        raise ValueError()
    access = None
    if access_token is not None:
        if type(access_token) is not SecretStr:
            raise ValueError()
        access = access_token.get_secret_value()
        if re.fullmatch(r"[\x21-\x7e]{1,16384}", access, re.ASCII) is None:
            raise ValueError()
    if "at_hash" in values:
        if access is None or len(_base64url(values["at_hash"], 22)) != 16:
            raise ValueError()
    return identity, issued, expires, authenticated, tuple(methods), access


def verify_id_token(
    token: SecretStr,
    jwks_bytes: bytes,
    attempt: LoginAttempt,
    now: int,
    *,
    access_token: SecretStr | None = None,
) -> VerifiedTokenEvidence:
    """Verify a bounded RS256/TOTP profile using an explicitly supplied trusted key set.

    JWKS provenance/custody is the caller's responsibility. Invalid key snapshots
    are unavailable configuration; unauthorized/malformed tokens are denied. No
    unknown-key retry, metadata fetch, state consumption or owner authorization
    occurs. Public results deliberately contain no tokens, nonce or key material.
    """
    if type(attempt) is not LoginAttempt:
        raise AuthenticationDenied()
    attempt.require_live(now)
    keys = _keys(jwks_bytes)
    try:
        if type(token) is not SecretStr:
            raise ValueError()
        compact = token.get_secret_value()
        if not 1 <= len(compact) <= MAX_TOKEN_BYTES or not compact.isascii():
            raise ValueError()
        segments = compact.split(".")
        if len(segments) != 3:
            raise ValueError()
        header = _object(_base64url(segments[0], 2731), 2048)
        claims = _object(_base64url(segments[1], 10923), 8192)
        signature = _base64url(segments[2], 684)
        if (
            not {"alg", "kid"} <= header.keys()
            or not header.keys() <= {"alg", "kid", "typ"}
            or header["alg"] != "RS256"
            or ("typ" in header and header["typ"] != "JWT")
        ):
            raise ValueError()
        key_id = _kid(header["kid"])
        if key_id not in keys:
            raise ValueError()
        key, signature_size = keys[key_id]
        if len(signature) != signature_size:
            raise ValueError()
        verified = jwt.decode(compact, key, algorithms=["RS256"], decoder_cls=_StrictDecoder)
        if verified.header != header or verified.claims != claims:
            raise ValueError()
        identity, issued, expires, authenticated, methods, access = _claims(
            claims, attempt, now, access_token
        )
        options: dict[str, Any] = {
            name: {"essential": True}
            for name in ("iss", "sub", "aud", "exp", "iat", "auth_time", "nonce", "amr")
        }
        options["iss"]["value"] = attempt.client.issuer
        params = {
            "client_id": attempt.client.client_id,
            "nonce": attempt.nonce.get_secret_value(),
            "max_age": attempt.max_age,
            "access_token": access,
        }
        _claim_validator(claims, header, options, params).validate(now, CLOCK_SKEW_SECONDS)
        return _VerifiedTokenEvidence(
            identity, attempt.client.client_id, issued, expires, authenticated, methods
        )
    except ValueError, TypeError, KeyError, RecursionError, JoseError:
        raise AuthenticationDenied() from None
