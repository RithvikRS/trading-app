"""Synthetic provider responses; never imported by deployed application modules."""

import json
import time
from uuid import UUID

import httpx2 as httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import ec
from pydantic import SecretStr

from trading_auth.config import AuthSettings
from trading_auth.models import AuthenticationDenied, OwnerBinding
from trading_auth.supabase import SupabaseProvider

PROJECT = "https://abcdefghijklmnopqrst.supabase.co"
ISSUER = PROJECT + "/auth/v1"
SUBJECT = UUID("20000000-0000-4000-8000-000000000001")
OWNER = UUID("10000000-0000-4000-8000-000000000001")
SESSION = UUID("30000000-0000-4000-8000-000000000001")
FACTOR = UUID("40000000-0000-4000-8000-000000000001")
CHALLENGE = UUID("50000000-0000-4000-8000-000000000001")
PASSWORD = SecretStr("synthetic-password-never-log")
SETUP = "JBSWY3DPEHPK3PXP"


class IdentityStub:
    def __init__(self):
        self.binding = OwnerBinding(OWNER, False)
        self.calls = []

    def lookup(self, issuer, subject):
        self.calls.append((issuer, subject))
        return self.binding if (issuer, subject) == (ISSUER, SUBJECT) else None

    def complete_enrollment(self, issuer, subject, owner):
        if self.binding is None or self.binding.owner_id != owner:
            raise AuthenticationDenied()
        self.binding = OwnerBinding(owner, True)


class SupabaseStub:
    def __init__(self):
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.jwk = json.loads(jwt.algorithms.ECAlgorithm.to_jwk(self.key.public_key()))
        self.jwk.update(kid="synthetic-signing-key", alg="ES256", use="sig")
        self.factors = [dict(id=str(FACTOR), factor_type="totp", status="verified")]
        self.requests = []
        self.overrides = {}
        self.claim_changes = {}
        self.header_changes = {}
        self.settings = dict(
            disable_signup=True,
            mailer_autoconfirm=False,
            saml_enabled=False,
            passkeys_enabled=False,
            external=dict(email=True, phone=False, anonymous_users=False),
        )
        self.discarded = 0

    def claims(self, mfa=False):
        now = int(time.time())
        result = dict(
            iss=ISSUER,
            sub=str(SUBJECT),
            aud="authenticated",
            role="authenticated",
            exp=now + 600,
            iat=now,
            aal="aal2" if mfa else "aal1",
            session_id=str(SESSION),
            is_anonymous=False,
            amr=[dict(method="password", timestamp=now)],
        )
        if mfa:
            result["amr"].append(dict(method="totp", timestamp=now))
        result.update(self.claim_changes)
        return result

    def token(self, mfa=False):
        return jwt.encode(
            self.claims(mfa),
            self.key,
            algorithm="ES256",
            headers={"kid": "synthetic-signing-key", **self.header_changes},
        )

    def tokens(self, mfa=False):
        return dict(
            access_token=self.token(mfa),
            refresh_token="synthetic-refresh-token-value",
            token_type="bearer",
        )

    def handle(self, request):
        self.requests.append(request)
        path = request.url.path.removeprefix("/auth/v1")
        if path in self.overrides:
            result = self.overrides[path]
            return result(request) if callable(result) else result
        if path == "/settings":
            return httpx.Response(200, json=self.settings)
        if path == "/.well-known/jwks.json":
            return httpx.Response(200, json={"keys": [self.jwk]})
        if path == "/token":
            assert request.url.query == b"grant_type=password"
            assert json.loads(request.content)["password"] == PASSWORD.get_secret_value()
            return httpx.Response(200, json=self.tokens())
        if path == "/user":
            return httpx.Response(
                200,
                json=dict(
                    id=str(SUBJECT),
                    role="authenticated",
                    is_anonymous=False,
                    email_confirmed_at="2026-01-01T00:00:00Z",
                    factors=self.factors,
                ),
            )
        if path == "/factors":
            self.factors.append(dict(id=str(FACTOR), factor_type="totp", status="unverified"))
            return httpx.Response(
                200,
                json=dict(
                    id=str(FACTOR),
                    type="totp",
                    totp=dict(
                        secret=SETUP,
                        qr_code="<svg>untrusted</svg>",
                        uri="https://untrusted.invalid",
                    ),
                ),
            )
        if path == f"/factors/{FACTOR}/challenge":
            return httpx.Response(
                200, json=dict(id=str(CHALLENGE), expires_at=int(time.time()) + 300)
            )
        if path == f"/factors/{FACTOR}/verify":
            if json.loads(request.content)["code"] != "123456":
                return httpx.Response(422, json={"msg": "synthetic-private-provider-detail"})
            self.factors[0]["status"] = "verified"
            return httpx.Response(200, json=self.tokens(True))
        if path == "/logout":
            assert request.url.query == b"scope=local"
            self.discarded += 1
            return httpx.Response(204)
        raise AssertionError("Unexpected provider operation")

    def provider(self):
        return SupabaseProvider(
            AuthSettings(
                project_url=PROJECT,
                publishable_key=SecretStr("sb_publishable_synthetic_test_key_only"),
            ),
            transport=httpx.MockTransport(self.handle),
        )
