"""The packaged process cannot opt into local credentials or elevated execution."""

from unittest.mock import Mock

import pytest

from trading_api import packaged


@pytest.mark.parametrize("reason", ["argument", "configuration", "root", "platform"])
def test_unsafe_package_startup_fails_without_loading_application(monkeypatch, reason, caplog):
    monkeypatch.setattr(packaged.sys, "argv", ["packaged"])
    monkeypatch.setattr(packaged.sys, "platform", "linux")
    monkeypatch.setattr(packaged.os, "getuid", lambda: 10001, raising=False)
    monkeypatch.setattr(packaged.os, "environ", {})
    monkeypatch.setattr(packaged, "configure_logging", lambda: None)
    factory, serve = Mock(), Mock()
    monkeypatch.setattr(packaged, "create_app", factory)
    monkeypatch.setattr(packaged.uvicorn, "run", serve)
    if reason == "argument":
        packaged.sys.argv.append("synthetic-private-argument")
    elif reason == "configuration":
        packaged.os.environ["TRADING_API_AUTH_ENABLED"] = "synthetic-private-value"
    elif reason == "root":
        monkeypatch.setattr(packaged.os, "getuid", lambda: 0)
    else:
        monkeypatch.setattr(packaged.sys, "platform", "win32")
    assert packaged.main() == 2
    factory.assert_not_called()
    serve.assert_not_called()
    assert "configuration_invalid" in caplog.text
    assert "synthetic-private" not in caplog.text
