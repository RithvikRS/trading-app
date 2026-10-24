import secrets

import pytest

from trading_auth.models import AuthenticationDenied, AuthenticationUnavailable
from trading_auth.session_models import Vault, new_cookie, verifier


def test_view_context_is_stable_separated_and_never_a_cookie_or_its_verifier():
    secret = secrets.token_bytes(32)
    vault = Vault(secret)
    cookie = new_cookie()
    key = verifier(cookie)
    context = vault.workspace_context(key)
    assert len(context) == 64 and bytes.fromhex(context)
    assert context not in {cookie, key.hex(), vault.csrf_secret, vault.rate_key(cookie).hex()}
    assert context == Vault(secret).workspace_context(key)
    assert context != vault.workspace_context(verifier(new_cookie()))
    assert context != Vault(secrets.token_bytes(32)).workspace_context(key)
    with pytest.raises(AuthenticationDenied):
        verifier(context)


@pytest.mark.parametrize("key", [b"", b"x" * 31, b"x" * 33, "x" * 32, None])
def test_context_derivation_rejects_non_verifier_inputs(key):
    with pytest.raises(AuthenticationUnavailable):
        Vault(secrets.token_bytes(32)).workspace_context(key)
