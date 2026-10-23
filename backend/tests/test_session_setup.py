import os

import pytest

from trading_api.application import create_app
from trading_api.config import ConfigurationError, Settings, load_settings
from trading_auth import local
from trading_auth.models import AuthenticationUnavailable


def test_key_initialization_is_explicit_private_and_never_overwrites(monkeypatch, tmp_path, capsys):
    key = tmp_path / "session.key"
    monkeypatch.setattr(local, "KEY_PATH", key)
    monkeypatch.setattr(local, "private_directory", lambda _: None)
    local.initialize_key()
    original = key.read_bytes()
    assert len(original) == 32
    if os.name != "nt":
        assert key.stat().st_mode & 0o077 == 0
    with pytest.raises(FileExistsError):
        local.initialize_key()
    assert key.read_bytes() == original
    assert not capsys.readouterr().out


def test_enabled_auth_fails_closed_without_configuration(monkeypatch):
    for name in ("TRADING_AUTH_PROJECT_URL", "TRADING_AUTH_PUBLISHABLE_KEY"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(AuthenticationUnavailable):
        create_app(Settings(auth_enabled=True))
    assert load_settings({"TRADING_API_AUTH_ENABLED": "true"}).auth_enabled
    with pytest.raises(ConfigurationError):
        load_settings({"TRADING_API_AUTH_ENABLED": "yes"})
