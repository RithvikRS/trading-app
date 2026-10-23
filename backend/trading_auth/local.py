"""Explicit local session-key custody; no key material is printed or put in PostgreSQL."""

import os
import secrets

from trading_auth.browser import BrowserAuth
from trading_auth.config import load_settings
from trading_auth.models import AuthenticationUnavailable
from trading_auth.session_models import Vault
from trading_auth.supabase import SupabaseProvider
from trading_db.local import ROOT, development, private_directory
from trading_db.sessions import SessionDatabase

KEY_PATH = ROOT / ".cache/auth/session.key"


def initialize_key() -> None:
    private_directory(KEY_PATH.parent)
    if KEY_PATH.is_symlink():
        raise AuthenticationUnavailable()
    # Exclusive create: restarting/setup never silently rotates a key and resets admission.
    with KEY_PATH.open("xb") as stream:
        stream.write(secrets.token_bytes(32))
    KEY_PATH.chmod(0o600)


def local_browser() -> BrowserAuth:
    try:
        config = load_settings()
        if KEY_PATH.is_symlink() or KEY_PATH.parent.is_symlink():
            raise AuthenticationUnavailable()
        if os.name != "nt" and KEY_PATH.stat().st_mode & 0o077:
            raise AuthenticationUnavailable()
        key = KEY_PATH.read_bytes()
        if len(key) != 32:
            raise AuthenticationUnavailable()
        service = development()
        store = SessionDatabase(service.url("auth"), service.project)
        return BrowserAuth(
            SupabaseProvider(config),
            store,
            Vault(key),
            recovery_email=config.recovery_email_enabled,
        )
    except Exception:
        raise AuthenticationUnavailable() from None
