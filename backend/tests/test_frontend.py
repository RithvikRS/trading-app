"""Static shell delivery cannot publish the demo, source tree, or private files."""

from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from trading_api import frontend
from trading_api.application import create_app
from trading_api.config import ConfigurationError, Settings, load_settings
from trading_auth.browser import BrowserAuth


@pytest.fixture
def build(tmp_path, monkeypatch):
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "assets").mkdir()
    (root / "index.html").write_text("<html>Private workspace</html>")
    (root / "assets/index-abcdefgh.js").write_text("// public application")
    (root / "assets/index-abcdefgh.css").write_text("body {}")
    (root / "assets/inter-abcdefgh.woff2").write_bytes(b"public-font")
    monkeypatch.setattr(frontend, "BUILD", root)
    return root


def test_frontend_is_explicitly_opt_in_and_has_no_auth_bypass(build):
    assert not load_settings({}).frontend_enabled
    assert load_settings({"TRADING_API_FRONTEND_ENABLED": "true"}).frontend_enabled
    for value in ["1", "yes", "True", ""]:
        with pytest.raises(ConfigurationError):
            load_settings({"TRADING_API_FRONTEND_ENABLED": value})
    with TestClient(
        create_app(Settings(frontend_enabled=True)), base_url="http://127.0.0.1:8000"
    ) as client:
        assert client.get("/").status_code == 200
        assert client.get("/api/v1/auth/bootstrap").status_code == 404
        assert client.get("/api/v1/workspace").status_code == 404


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/assets/index-abcdefgh.js",
        "/assets/index-abcdefgh.css",
        "/assets/inter-abcdefgh.woff2",
    ],
)
def test_only_public_build_files_are_served_without_caching(build, path):
    with TestClient(
        create_app(Settings(frontend_enabled=True)), base_url="http://127.0.0.1:8000"
    ) as client:
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["content-security-policy"] == frontend.CONTENT_POLICY
        assert "unsafe-inline" not in response.headers["content-security-policy"]
        assert response.headers["x-frame-options"] == "DENY"
        assert response.headers["referrer-policy"] == "no-referrer"
        assert "set-cookie" not in response.headers
        assert "access-control-allow-origin" not in response.headers
        assert client.post(path, json={}).status_code == 405


@pytest.mark.parametrize(
    "path",
    [
        "/?secret=example",
        "/index.html",
        "/assets/missing.js",
        "/assets/index-abcdefgh.js?token=example",
        "/src/main.tsx",
        "/demo",
        "/.env",
        "/assets/../../.env",
        "/assets/%2e%2e%2f.env",
        "/api/v1/unknown",
        "/sw.js",
    ],
)
def test_no_fallback_path_traversal_source_or_queries(build, path):
    with TestClient(
        create_app(Settings(frontend_enabled=True)), base_url="http://127.0.0.1:8000"
    ) as client:
        response = client.get(path)
        assert response.status_code == 404
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["content-security-policy"].startswith("default-src 'none'; frame")
        assert "Private workspace" not in response.text


@pytest.mark.parametrize(
    "filename", [".env", "assets/index.js.map", "demo.html", "assets/private.json"]
)
def test_unexpected_build_files_fail_startup(build, filename):
    (build / filename).write_text("synthetic-private-value")
    with pytest.raises(ValueError, match="Unexpected protected build file"):
        create_app(Settings(frontend_enabled=True))


def test_missing_incomplete_or_oversized_build_fails_startup(build):
    (build / "index.html").unlink()
    with pytest.raises(ValueError, match="Incomplete"):
        create_app(Settings(frontend_enabled=True))
    (build / "index.html").write_bytes(b"x" * 2_000_001)
    with pytest.raises(ValueError, match="size limit"):
        create_app(Settings(frontend_enabled=True))


def test_build_is_loaded_once_and_does_not_read_request_paths(build):
    app = create_app(Settings(frontend_enabled=True))
    (build / "index.html").write_text("changed-on-disk")
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        assert "changed-on-disk" not in client.get("/").text
        assert "Private workspace" in client.get("/").text


@pytest.mark.parametrize("enabled", [False, True])
def test_bootstrap_reports_only_recovery_capability_and_sets_no_session(enabled):
    browser = Mock(spec=BrowserAuth)
    browser.recovery_email = enabled
    browser.vault = Mock(csrf_secret="synthetic-csrf-signing-key")
    with TestClient(
        create_app(Settings(), browser=browser), base_url="http://127.0.0.1:8000"
    ) as client:
        response = client.get("/api/v1/auth/bootstrap")
        assert response.json() == {"status": "ready", "recovery_email_enabled": enabled}
        assert "trading_dev_csrf" in client.cookies
        assert "trading_dev_session" not in client.cookies
        assert response.headers["cache-control"] == "no-store"
        browser.start.assert_not_called()
