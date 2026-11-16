"""Local authorization request preparation; no IdP access or browser session."""

import base64
import hashlib
import secrets
from urllib.parse import urlencode

from pydantic import SecretStr

from trading_auth.models import AuthenticationDenied
from trading_oidc.contracts import ATTEMPT_SECONDS, LoginAttempt, OidcClient


def create_attempt(client: OidcClient, admitted_at: int, *, max_age: int = 300) -> LoginAttempt:
    """Generate separate random protocol secrets for future server-side custody."""
    if type(admitted_at) is not int:
        raise AuthenticationDenied()
    return LoginAttempt(
        client=client,
        state=SecretStr(secrets.token_urlsafe(32)),
        nonce=SecretStr(secrets.token_urlsafe(32)),
        pkce_verifier=SecretStr(secrets.token_urlsafe(32)),
        browser_binding=SecretStr(secrets.token_urlsafe(32)),
        admitted_at=admitted_at,
        expires_at=admitted_at + ATTEMPT_SECONDS,
        max_age=max_age,
    )


def authorization_url(attempt: LoginAttempt, now: int) -> SecretStr:
    """Build only a code/S256 request. The result contains private attempt values.

    Requesting essential AMR/auth_time does not establish MFA; the later signed
    token verifier must enforce the selected assurance and freshness policy.
    """
    if type(attempt) is not LoginAttempt:
        raise AuthenticationDenied()
    attempt.require_live(now)
    challenge = (
        base64.urlsafe_b64encode(
            hashlib.sha256(attempt.pkce_verifier.get_secret_value().encode("ascii")).digest()
        )
        .rstrip(b"=")
        .decode("ascii")
    )
    return SecretStr(
        attempt.client.authorization_endpoint
        + "?"
        + urlencode(
            {
                "client_id": attempt.client.client_id,
                "redirect_uri": attempt.client.redirect_uri,
                "response_type": "code",
                "response_mode": "query",
                "scope": "openid",
                "state": attempt.state.get_secret_value(),
                "nonce": attempt.nonce.get_secret_value(),
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "max_age": str(attempt.max_age),
                "claims": '{"id_token":{"amr":{"essential":true},"auth_time":{"essential":true}}}',
            }
        )
    )
