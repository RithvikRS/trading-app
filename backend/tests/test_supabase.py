import json
import time

import httpx2 as httpx
import jwt
import pytest
from auth_support import ISSUER, PASSWORD, PROJECT, SUBJECT, SupabaseStub
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from pydantic import SecretStr, ValidationError

from trading_auth.config import AuthSettings, load_settings
from trading_auth.models import (
    AuthenticationDenied,
    AuthenticationLimited,
    AuthenticationUnavailable,
)


@pytest.mark.parametrize(
    "target",
    [
        "http://abcdefghijklmnopqrst.supabase.co",
        "https://evil.invalid",
        PROJECT + "/",
        PROJECT + ":443",
        PROJECT + "@evil.invalid",
        PROJECT + "?x=1",
        "http://127.0.0.1:54321",
        PROJECT.upper(),
    ],
)
def test_provider_target_has_no_redirect_or_plaintext_escape(target):
    with pytest.raises(ValidationError):
        AuthSettings(
            project_url=target, publishable_key=SecretStr("sb_publishable_synthetic_test_key_only")
        )


@pytest.mark.parametrize(
    "key",
    [
        "sb_secret_synthetic_secret_key_only",
        "eyJ.synthetic.legacy",
        "",
        "sb_publishable_short",
        "sb_publishable_" + "x" * 201,
    ],
)
def test_runtime_rejects_admin_and_legacy_keys(key):
    with pytest.raises(ValidationError):
        AuthSettings(project_url=PROJECT, publishable_key=SecretStr(key))


def test_provider_configuration_has_no_test_identity_or_unsafe_overrides():
    for key in ("TEST_IDENTITY", "VERIFY_TLS", "SERVICE_ROLE_KEY", "ALLOW_SIGNUP", "JWT_SECRET"):
        with pytest.raises(AuthenticationUnavailable):
            load_settings({"TRADING_AUTH_" + key: "synthetic-secret"})


@pytest.fixture
def provider():
    upstream = SupabaseStub()
    client = upstream.provider()
    try:
        yield upstream, client
    finally:
        client.close()


def test_valid_claims_verified_with_fixed_project_jwks(provider):
    upstream, client = provider
    tokens = client.password("owner@example.invalid", PASSWORD)
    assert tokens.identity.subject == SUBJECT
    assert tokens.identity.issuer == ISSUER
    assert "synthetic-refresh" not in repr(tokens)
    for request in upstream.requests:
        assert str(request.url).startswith(ISSUER + "/")
        assert request.headers["accept-encoding"] == "identity"
    assert client._http.follow_redirects is False
    assert client._http.trust_env is False


@pytest.mark.parametrize(
    "change",
    [
        {"iss": "https://other.supabase.co/auth/v1"},
        {"aud": "service_role"},
        {"aud": ["authenticated"]},
        {"role": "service_role"},
        {"is_anonymous": True},
        {"is_anonymous": None},
        {"sub": "not-a-uuid"},
        {"sub": "00000000-0000-0000-0000-000000000000"},
        {"aal": "aal2"},
        {"session_id": "not-a-session"},
        {"amr": []},
        {"exp": "synthetic"},
        {"iat": False},
    ],
)
def test_signed_but_inappropriate_identity_claims_are_rejected(provider, change):
    upstream, client = provider
    upstream.claim_changes = change
    with pytest.raises(AuthenticationDenied):
        client.password("owner@example.invalid", PASSWORD)


@pytest.mark.parametrize(
    "case",
    [
        "expired",
        "future",
        "long_lifetime",
        "stale_password",
        "no_password",
        "missing_subject",
        "bad_signature",
        "wrong_kid",
        "foreign_key_url",
        "symmetric",
    ],
)
def test_tamper_lifetime_and_claim_requirements(provider, case):
    upstream, client = provider
    now = int(time.time())
    if case == "expired":
        upstream.claim_changes["exp"] = now - 1
    elif case == "future":
        upstream.claim_changes["iat"] = now + 30
    elif case == "long_lifetime":
        upstream.claim_changes["exp"] = now + 3601
    elif case == "stale_password":
        upstream.claim_changes["amr"] = [dict(method="password", timestamp=now - 301)]
    elif case == "no_password":
        upstream.claim_changes["amr"] = [dict(method="recovery", timestamp=now)]
    elif case == "missing_subject":
        claims = upstream.claims()
        del claims["sub"]
        encoded = jwt.encode(
            claims, upstream.key, algorithm="ES256", headers={"kid": "synthetic-signing-key"}
        )
        upstream.overrides["/token"] = httpx.Response(
            200, json={**upstream.tokens(), "access_token": encoded}
        )
    elif case == "bad_signature":
        upstream.key = ec.generate_private_key(ec.SECP256R1())
    elif case == "wrong_kid":
        upstream.header_changes["kid"] = "other-key"
    elif case == "foreign_key_url":
        upstream.header_changes["jku"] = "https://attacker.invalid/keys"
    elif case == "symmetric":
        encoded = jwt.encode(
            upstream.claims(),
            "synthetic-test-key-long-enough-for-hs256",
            algorithm="HS256",
            headers={"kid": "synthetic-signing-key"},
        )
        upstream.overrides["/token"] = httpx.Response(
            200, json={**upstream.tokens(), "access_token": encoded}
        )
    with pytest.raises(AuthenticationDenied):
        client.password("owner@example.invalid", PASSWORD)
    assert all(
        request.url.host == "abcdefghijklmnopqrst.supabase.co" for request in upstream.requests
    )


@pytest.mark.parametrize(
    "change",
    [
        {"disable_signup": False},
        {"mailer_autoconfirm": True},
        {"saml_enabled": True},
        {"passkeys_enabled": True},
        {"external": dict(email=True, anonymous_users=True)},
        {"external": dict(email=True, anonymous_users=False, google=True)},
        {"external": dict(email=False, anonymous_users=False)},
    ],
)
def test_provider_registration_and_signin_settings_fail_closed(provider, change):
    upstream, client = provider
    upstream.settings.update(change)
    with pytest.raises(AuthenticationUnavailable):
        client.password("owner@example.invalid", PASSWORD)
    assert len(upstream.requests) == 1


@pytest.mark.parametrize(
    "status,exception",
    [
        (302, AuthenticationUnavailable),
        (401, AuthenticationDenied),
        (422, AuthenticationDenied),
        (429, AuthenticationLimited),
        (500, AuthenticationUnavailable),
    ],
)
def test_provider_errors_are_generic_and_redirects_are_not_followed(provider, status, exception):
    upstream, client = provider
    upstream.overrides["/settings"] = httpx.Response(
        status, text="synthetic-private-detail", headers={"location": "https://attacker.invalid"}
    )
    with pytest.raises(exception) as error:
        client.password("owner@example.invalid", PASSWORD)
    assert "synthetic-private-detail" not in str(error.value)
    assert len(upstream.requests) == 1


@pytest.mark.parametrize(
    "kind", ["oversize", "html", "list", "invalid_json", "encoding", "timeout"]
)
def test_bounded_provider_response_and_outage_handling(provider, kind):
    upstream, client = provider
    responses = {
        "oversize": httpx.Response(200, json={"unexpected": "x" * 65536}),
        "html": httpx.Response(200, text="<html>private</html>"),
        "list": httpx.Response(200, json=[]),
        "invalid_json": httpx.Response(
            200, content=b"{bad", headers={"content-type": "application/json"}
        ),
        "encoding": httpx.Response(
            200,
            content=b"{}",
            headers={"content-type": "application/json", "content-encoding": "identity-other"},
        ),
    }
    if kind == "timeout":

        def timeout(request):
            raise httpx.ReadTimeout("synthetic-private-url")

        upstream.overrides["/settings"] = timeout
    else:
        upstream.overrides["/settings"] = responses[kind]
    with pytest.raises(AuthenticationUnavailable) as error:
        client.password("owner@example.invalid", PASSWORD)
    assert "private" not in str(error.value)


def test_jwks_failure_does_not_use_unverified_claims(provider):
    upstream, client = provider
    upstream.overrides["/.well-known/jwks.json"] = httpx.Response(503)
    with pytest.raises(AuthenticationUnavailable):
        client.password("owner@example.invalid", PASSWORD)


def test_key_rotation_fetches_current_keys_without_stale_fallback(provider):
    upstream, client = provider
    client.password("owner@example.invalid", PASSWORD)
    upstream.key = ec.generate_private_key(ec.SECP256R1())
    upstream.jwk = json.loads(jwt.algorithms.ECAlgorithm.to_jwk(upstream.key.public_key()))
    upstream.jwk.update(kid="rotated", alg="ES256", use="sig")
    upstream.header_changes["kid"] = "rotated"
    assert client.password("owner@example.invalid", PASSWORD).identity.subject == SUBJECT


def test_rsa_signing_key_is_verified_with_matching_declared_algorithm(provider):
    upstream, client = provider
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    upstream.jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    upstream.jwk.update(kid="rsa-key", alg="RS256", use="sig")
    access = jwt.encode(upstream.claims(), key, algorithm="RS256", headers={"kid": "rsa-key"})
    upstream.overrides["/token"] = httpx.Response(
        200, json={**upstream.tokens(), "access_token": access}
    )
    assert client.password("owner@example.invalid", PASSWORD).identity.subject == SUBJECT


@pytest.mark.parametrize("change", [{"alg": "RS256"}, {"use": "enc"}, {"crv": "P-384"}])
def test_jwk_key_metadata_cannot_change_verification_algorithm(provider, change):
    upstream, client = provider
    upstream.jwk.update(change)
    with pytest.raises(AuthenticationDenied):
        client.password("owner@example.invalid", PASSWORD)


def test_provider_user_subject_and_confirmed_status_are_rechecked(provider):
    upstream, client = provider
    tokens = client.password("owner@example.invalid", PASSWORD)
    upstream.overrides["/user"] = httpx.Response(
        200,
        json={
            "id": str(SUBJECT),
            "is_anonymous": False,
            "role": "authenticated",
            "email_confirmed_at": None,
        },
    )
    with pytest.raises(AuthenticationDenied):
        client.factors(tokens)


def test_existing_http_application_still_exposes_no_auth_bypass():
    from starlette.testclient import TestClient

    from trading_api.application import create_app

    with TestClient(create_app(), base_url="http://127.0.0.1") as client:
        for path in (
            "login",
            "signup",
            "mfa/enroll",
            "mfa/verify",
            "test-login",
            "provision-owner",
        ):
            response = client.post("/api/v1/auth/" + path, json={"owner_id": "arbitrary"})
            assert response.status_code == 404
            assert response.headers["cache-control"] == "no-store"
