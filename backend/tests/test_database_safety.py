"""Configuration refusals happen before network access or destructive setup."""

from unittest.mock import patch

import pytest
from sqlalchemy import URL

from trading_db import __main__ as cli
from trading_db import local
from trading_db.connections import DatabaseFailure, engine_for, require_disposable
from trading_db.local import LocalService, execute, local_context


def local_test_url() -> URL:
    return URL.create(
        "postgresql+psycopg",
        username="trading_migrator",
        password="synthetic",
        host="127.0.0.1",
        port=55433,
        database="trading_test",
    )


@pytest.mark.parametrize(
    "change",
    [
        {"host": "db.example.supabase.co"},
        {"host": "localhost"},
        {"host": "::1"},
        {"host": "/tmp/socket"},
        {"database": "trading_dev"},
        {"database": "postgres"},
        {"database": "production_test"},
        {"drivername": "sqlite"},
        {"username": "postgres"},
        {"port": 543},
        {"query": {"host": "db.example.supabase.co"}},
        {"query": {"options": "-c role=trading_bootstrap"}},
    ],
)
def test_unsafe_test_target_refused_before_connect(change):
    with patch("trading_db.connections.create_engine") as create:
        with pytest.raises(DatabaseFailure):
            require_disposable(local_test_url().set(**change), "trading-test-0123456789abcdef")
    create.assert_not_called()


@pytest.mark.parametrize(
    "project", ["trading-development", "trading-test", "other-0123456789abcdef"]
)
def test_test_marker_required_before_connect(project):
    with patch("trading_db.connections.create_engine") as create:
        with pytest.raises(DatabaseFailure):
            require_disposable(local_test_url(), project)
    create.assert_not_called()


def test_regular_engine_rejects_hosted_url():
    with patch("trading_db.connections.create_engine") as create:
        with pytest.raises(DatabaseFailure):
            engine_for(local_test_url().set(host="remote.invalid"))
    create.assert_not_called()


def test_remote_docker_context_is_rejected(monkeypatch):
    for key in ("DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_TLS_VERIFY"):
        monkeypatch.delenv(key, raising=False)
    with patch("trading_db.local.execute", side_effect=["remote", "ssh://host.invalid"]):
        with pytest.raises(DatabaseFailure):
            local_context()


def test_docker_override_is_rejected_before_command(monkeypatch):
    monkeypatch.setenv("DOCKER_HOST", "tcp://host.invalid")
    with patch("trading_db.local.execute") as command:
        with pytest.raises(DatabaseFailure):
            local_context()
    command.assert_not_called()


def test_unknown_project_cannot_be_cleaned(tmp_path):
    service = LocalService("test", "trading-development", tmp_path, "default")
    with patch.object(LocalService, "compose") as compose:
        with pytest.raises(DatabaseFailure):
            service.down()
    compose.assert_not_called()


def test_cli_does_not_print_database_errors_or_secrets(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["trading_db", "up"])
    with patch("trading_db.__main__.development", side_effect=RuntimeError("synthetic-secret")):
        assert cli.main() == 1
    captured = capsys.readouterr()
    assert "synthetic-secret" not in captured.out + captured.err
    assert "Database operation failed" in captured.err


def test_docker_failure_does_not_disclose_captured_output():
    import subprocess

    result = subprocess.CompletedProcess([], 1, "synthetic-secret", "synthetic-secret")
    with patch("trading_db.local.subprocess.run", return_value=result):
        with pytest.raises(DatabaseFailure) as error:
            execute(["docker"])
    assert "synthetic-secret" not in str(error.value)


def test_failed_container_cleanup_retains_local_recovery_files(monkeypatch, tmp_path):
    monkeypatch.setattr(local, "CACHE", tmp_path)
    monkeypatch.setattr(local, "private_directory", lambda path: path.mkdir(exist_ok=True))
    monkeypatch.setattr(local, "local_context", lambda: "default")
    monkeypatch.setattr(LocalService, "up", lambda self: None)
    with patch.object(LocalService, "down", side_effect=DatabaseFailure("Docker unavailable")):
        with pytest.raises(DatabaseFailure):
            with local.disposable() as service:
                (service.directory / "recovery").write_text("synthetic fixture")
    assert (service.directory / "recovery").read_text() == "synthetic fixture"


def test_partial_credentials_fail_without_replacing_existing_file(monkeypatch, tmp_path):
    monkeypatch.setattr(local, "private_directory", lambda path: None)
    service = LocalService("development", "trading-development", tmp_path, "default")
    (tmp_path / "bootstrap").write_text("synthetic-original")
    with pytest.raises(DatabaseFailure, match="Incomplete"):
        service.initialize()
    assert (tmp_path / "bootstrap").read_text() == "synthetic-original"
    assert not (tmp_path / "runtime").exists()


def test_auth_credential_upgrade_preserves_original_passwords(monkeypatch, tmp_path):
    monkeypatch.setattr(local, "private_directory", lambda path: None)
    service = LocalService("development", "trading-development", tmp_path, "default")
    originals = {
        role: str(index) * 64 for index, role in enumerate(("bootstrap", "migrator", "runtime"), 1)
    }
    for role, value in originals.items():
        (tmp_path / role).write_text(value)
    service.initialize()
    for role, value in originals.items():
        assert service.password(role) == value
    auth = service.password("auth")
    assert len(auth) == 64 and auth not in originals.values()
    service.initialize()
    assert service.password("auth") == auth
