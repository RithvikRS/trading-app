import secrets
import time
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import httpx2 as httpx
import pytest
from pydantic import SecretStr

from tests.auth_support import FACTOR, OWNER, PASSWORD
from tests.browser_support import BrowserProviderStub
from trading_auth.config import load_settings
from trading_auth.models import AuthenticationDenied, AuthenticationUnavailable
from trading_auth.session_models import SessionRow, SessionState, Vault, new_cookie, verifier


def test_ciphertext_authenticates_row_context_and_key_and_redacts_representations():
    stub = BrowserProviderStub()
    with_provider = stub.provider()
    try:
        tokens = with_provider.password("fixture@example.invalid", PASSWORD)
        state = SessionState.from_tokens(tokens, csrf="a" * 64, fresh_until=int(time.time()) + 300)
        vault = Vault(secrets.token_bytes(32))
        key = verifier(new_cookie())
        sealed = vault.seal(state, key)
        now = datetime.now(UTC)
        row = SessionRow(key, uuid4(), OWNER, "login", sealed, now, now, now, uuid4())
        assert vault.open(row) == state
        for mutated in (
            replace(row, verifier=verifier(new_cookie())),
            replace(row, sealed=sealed[:-1] + bytes([sealed[-1] ^ 1])),
        ):
            with pytest.raises(AuthenticationUnavailable):
                vault.open(mutated)
        with pytest.raises(AuthenticationUnavailable):
            Vault(secrets.token_bytes(32)).open(row)
        assert tokens.access.get_secret_value() not in repr(state)
        assert tokens.refresh.get_secret_value() not in repr(state)
    finally:
        with_provider.close()


def test_refresh_accepts_original_amr_but_never_treats_it_as_fresh_authentication():
    stub = BrowserProviderStub()
    provider = stub.provider()
    try:
        tokens = provider.password("fixture@example.invalid", PASSWORD)
        tokens = provider.verify(tokens, FACTOR, SecretStr("123456"))
        now = int(time.time())
        stub.claim_changes["amr"] = [
            {"method": method, "timestamp": now - 600} for method in ("password", "totp")
        ]
        assert provider.refresh(tokens).identity.aal == "aal2"
        with pytest.raises(AuthenticationDenied):
            provider.verify(tokens, FACTOR, SecretStr("123456"))
        stub.claim_changes["session_id"] = str(uuid4())
        with pytest.raises(AuthenticationDenied):
            provider.refresh(tokens)
    finally:
        provider.close()


@pytest.mark.parametrize(
    "change",
    [
        {"aal": "aal1"},
        {"sub": str(uuid4())},
        {"role": "service_role"},
        {"amr": [{"method": "password", "timestamp": int(time.time())}]},
    ],
)
def test_refresh_rejects_identity_or_assurance_downgrade(change):
    stub = BrowserProviderStub()
    provider = stub.provider()
    try:
        tokens = provider.verify(
            provider.password("fixture@example.invalid", PASSWORD), FACTOR, SecretStr("123456")
        )
        stub.claim_changes = change
        with pytest.raises(AuthenticationDenied):
            provider.refresh(tokens)
    finally:
        provider.close()


def test_recovery_token_is_otp_and_requires_existing_totp_for_aal2():
    stub = BrowserProviderStub()
    provider = stub.provider()
    try:
        recovered = provider.verify_recovery("fixture@example.invalid", SecretStr("654321"))
        assert recovered.identity.aal == "aal1"
        with pytest.raises(AuthenticationDenied):
            provider.verify(recovered, FACTOR, SecretStr("123456"))
        assert (
            provider.verify(recovered, FACTOR, SecretStr("123456"), primary="otp").identity.aal
            == "aal2"
        )
        stub.overrides["/verify"] = httpx.Response(
            302, headers={"location": "https://attacker.invalid"}
        )
        with pytest.raises(AuthenticationUnavailable):
            provider.verify_recovery("fixture@example.invalid", SecretStr("654321"))
    finally:
        provider.close()


def test_recovery_email_requires_explicit_configuration():
    values = {
        "TRADING_AUTH_PROJECT_URL": "https://abcdefghijklmnopqrst.supabase.co",
        "TRADING_AUTH_PUBLISHABLE_KEY": "sb_publishable_synthetic_test_key_only",
    }
    assert not load_settings(values).recovery_email_enabled
    assert load_settings(
        {**values, "TRADING_AUTH_RECOVERY_EMAIL_ENABLED": "true"}
    ).recovery_email_enabled
    with pytest.raises(AuthenticationUnavailable):
        load_settings({**values, "TRADING_AUTH_RECOVERY_EMAIL_ENABLED": "yes"})
