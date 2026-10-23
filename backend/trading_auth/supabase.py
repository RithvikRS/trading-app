"""Bounded Supabase Auth REST adapter; all identity claims are signature verified."""

import json
import re
import time
from typing import Any, cast
from uuid import UUID

import httpx2 as httpx
import jwt
from pydantic import SecretStr

from trading_auth.config import AuthSettings
from trading_auth.models import (
    AuthenticationDenied,
    AuthenticationLimited,
    AuthenticationUnavailable,
    Enrollment,
    Factor,
    Identity,
    Tokens,
)

MAX_RESPONSE = 65536


def uuid_value(value: Any) -> UUID:
    if not isinstance(value, str):
        raise AuthenticationDenied()
    try:
        result = UUID(value)
    except ValueError:
        raise AuthenticationDenied() from None
    if not result.int or str(result) != value:
        raise AuthenticationDenied()
    return result


class SupabaseProvider:
    def __init__(self, settings: AuthSettings, *, transport: httpx.BaseTransport | None = None):
        self.settings = AuthSettings.model_validate(settings.model_dump())
        # The transport seam is for deterministic tests, never selectable by environment.
        self._http = httpx.Client(
            timeout=httpx.Timeout(5, connect=3, pool=2),
            limits=httpx.Limits(max_connections=4, max_keepalive_connections=2),
            follow_redirects=False,
            trust_env=False,
            verify=True,
            transport=transport,
        )

    def close(self) -> None:
        self._http.close()

    def _request(
        self,
        method: str,
        path: str,
        *,
        token: SecretStr | None = None,
        payload: dict[str, Any] | None = None,
        empty: bool = False,
    ) -> dict[str, Any]:
        headers = {
            "apikey": self.settings.publishable_key.get_secret_value(),
            "Accept": "application/json",
            "Accept-Encoding": "identity",
        }
        if token is not None:
            headers["Authorization"] = "Bearer " + token.get_secret_value()
        started = time.monotonic()
        try:
            with self._http.stream(
                method,
                self.settings.issuer + path,
                headers=headers,
                json=payload,
            ) as response:
                if response.status_code == 429:
                    raise AuthenticationLimited()
                if response.status_code in {400, 401, 403, 404, 422}:
                    raise AuthenticationDenied()
                if response.status_code not in {200, 204}:
                    raise AuthenticationUnavailable()
                if empty:
                    return {}
                if (
                    response.headers.get("content-type", "").split(";")[0] != "application/json"
                    or response.headers.get("content-encoding", "identity") != "identity"
                ):
                    raise AuthenticationUnavailable()
                data = bytearray()
                for chunk in response.iter_bytes():
                    data.extend(chunk)
                    if len(data) > MAX_RESPONSE or time.monotonic() - started > 10:
                        raise AuthenticationUnavailable()
                parsed = json.loads(data)
                if not isinstance(parsed, dict):
                    raise AuthenticationUnavailable()
                return cast(dict[str, Any], parsed)
        except (httpx.HTTPError, ValueError, TypeError, RecursionError) as error:
            if isinstance(error, AuthenticationDenied):
                raise
            raise AuthenticationUnavailable() from None

    def _closed_registration(self) -> None:
        settings = self._request("GET", "/settings")
        external = settings.get("external")
        if (
            settings.get("disable_signup") is not True
            or settings.get("mailer_autoconfirm") is not False
            or settings.get("saml_enabled") is not False
            or settings.get("passkeys_enabled", False) is not False
            or not isinstance(external, dict)
            or external.get("email") is not True
            or external.get("anonymous_users") is not False
            or any(value is not False for key, value in external.items() if key != "email")
        ):
            raise AuthenticationUnavailable()

    def _identity(self, token: SecretStr, *, mfa: bool) -> Identity:
        raw = token.get_secret_value()
        if not 32 <= len(raw) <= 16384:
            raise AuthenticationDenied()
        try:
            header = jwt.get_unverified_header(raw)
            algorithm, kid = header.get("alg"), header.get("kid")
            if (
                algorithm not in {"ES256", "RS256"}
                or header.get("typ") != "JWT"
                or not isinstance(kid, str)
                or not 1 <= len(kid) <= 128
                or any(key in header for key in ("jku", "jwk", "x5u", "crit"))
            ):
                raise AuthenticationDenied()
            document = self._request("GET", "/.well-known/jwks.json")
            keys = document.get("keys")
            if not isinstance(keys, list) or not 1 <= len(keys) <= 10:
                raise AuthenticationDenied()
            selected = [key for key in keys if isinstance(key, dict) and key.get("kid") == kid]
            if len(selected) != 1:
                raise AuthenticationDenied()
            key = selected[0]
            if key.get("alg") != algorithm or key.get("use", "sig") != "sig":
                raise AuthenticationDenied()
            if (algorithm == "ES256" and (key.get("kty") != "EC" or key.get("crv") != "P-256")) or (
                algorithm == "RS256" and key.get("kty") != "RSA"
            ):
                raise AuthenticationDenied()
            claims = jwt.decode(
                raw,
                jwt.PyJWK.from_dict(key).key,
                algorithms=[algorithm],
                audience="authenticated",
                issuer=self.settings.issuer,
                options={
                    "require": ["iss", "sub", "aud", "exp", "iat", "aal", "session_id", "amr"],
                    "strict_aud": True,
                },
                leeway=0,
            )
            now = time.time()
            if (
                claims.get("role") != "authenticated"
                or claims.get("is_anonymous") is not False
                or claims.get("aal") != ("aal2" if mfa else "aal1")
                or type(claims["exp"]) is not int
                or type(claims["iat"]) is not int
                or not now - 300 <= claims["iat"] <= now
                or not claims["iat"] < claims["exp"] <= claims["iat"] + 3600
            ):
                raise AuthenticationDenied()
            methods = claims["amr"]
            if not isinstance(methods, list) or not 1 <= len(methods) <= 10:
                raise AuthenticationDenied()
            for required in ("password", "totp") if mfa else ("password",):
                if not any(
                    isinstance(item, dict)
                    and item.get("method") == required
                    and type(item.get("timestamp")) is int
                    and now - 300 <= item["timestamp"] <= now
                    for item in methods
                ):
                    raise AuthenticationDenied()
            return Identity(
                self.settings.issuer,
                uuid_value(claims["sub"]),
                uuid_value(claims["session_id"]),
                "aal2" if mfa else "aal1",
                claims["exp"],
            )
        except jwt.PyJWTError, ValueError, TypeError, KeyError, OverflowError:
            raise AuthenticationDenied() from None

    def _tokens(self, data: dict[str, Any], *, mfa: bool) -> Tokens:
        access, refresh = data.get("access_token"), data.get("refresh_token")
        if (
            data.get("token_type") != "bearer"
            or not isinstance(access, str)
            or not isinstance(refresh, str)
            or not 16 <= len(refresh) <= 4096
            or "weak_password" in data
        ):
            raise AuthenticationDenied()
        secret = SecretStr(access)
        return Tokens(secret, SecretStr(refresh), self._identity(secret, mfa=mfa))

    def password(self, email: str, password: SecretStr) -> Tokens:
        self._closed_registration()
        return self._tokens(
            self._request(
                "POST",
                "/token?grant_type=password",
                payload={"email": email, "password": password.get_secret_value()},
            ),
            mfa=False,
        )

    def factors(self, tokens: Tokens) -> tuple[Factor, ...]:
        user = self._request("GET", "/user", token=tokens.access)
        if (
            uuid_value(user.get("id")) != tokens.identity.subject
            or user.get("is_anonymous") is not False
            or user.get("role") != "authenticated"
            or not isinstance(user.get("email_confirmed_at"), str)
            or not user["email_confirmed_at"]
        ):
            raise AuthenticationDenied()
        rows = user.get("factors", [])
        if not isinstance(rows, list) or len(rows) > 10:
            raise AuthenticationDenied()
        result = []
        for row in rows:
            if (
                not isinstance(row, dict)
                or row.get("status") not in {"verified", "unverified"}
                or not isinstance(row.get("factor_type"), str)
            ):
                raise AuthenticationDenied()
            result.append(
                Factor(uuid_value(row.get("id")), row["factor_type"], row["status"] == "verified")
            )
        if len({factor.id for factor in result}) != len(result):
            raise AuthenticationDenied()
        return tuple(result)

    def enroll(self, tokens: Tokens) -> Enrollment:
        data = self._request(
            "POST",
            "/factors",
            token=tokens.access,
            payload={"factor_type": "totp", "friendly_name": "Portfolio authenticator"},
        )
        totp = data.get("totp")
        if (
            data.get("type") != "totp"
            or not isinstance(totp, dict)
            or not isinstance(totp.get("secret"), str)
            or not re.fullmatch(r"[A-Z2-7]{16,128}", totp["secret"])
        ):
            raise AuthenticationDenied()
        return Enrollment(uuid_value(data.get("id")), SecretStr(totp["secret"]))

    def verify(self, tokens: Tokens, factor: UUID, code: SecretStr) -> Tokens:
        challenge = self._request(
            "POST", f"/factors/{factor}/challenge", token=tokens.access, payload={}
        )
        identifier = uuid_value(challenge.get("id"))
        expires = challenge.get("expires_at")
        if type(expires) is not int or not time.time() < expires <= time.time() + 600:
            raise AuthenticationDenied()
        result = self._tokens(
            self._request(
                "POST",
                f"/factors/{factor}/verify",
                token=tokens.access,
                payload={"challenge_id": str(identifier), "code": code.get_secret_value()},
            ),
            mfa=True,
        )
        if (result.identity.subject, result.identity.session_id) != (
            tokens.identity.subject,
            tokens.identity.session_id,
        ):
            raise AuthenticationDenied()
        return result

    def discard(self, tokens: Tokens) -> None:
        self._request("POST", "/logout?scope=local", token=tokens.access, empty=True)
