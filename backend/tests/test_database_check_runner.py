"""A bounded database suite still cleans up and fails without exposing diagnostics."""

import subprocess
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from trading_db import __main__ as command


@pytest.mark.parametrize("outcome", ["success", "failed", "timeout"])
@pytest.mark.parametrize(
    ("platform", "environment", "timeout"),
    [
        ("nt", {}, 2700),
        ("posix", {}, 1080),
        ("nt", {"CI": "true"}, 1080),
        ("nt", {"CI": ""}, 1080),
        ("nt", {"GITHUB_ACTIONS": "true"}, 1080),
        ("nt", {"GITHUB_ACTIONS": ""}, 1080),
        ("posix", {"CI": "true", "GITHUB_ACTIONS": "true"}, 1080),
    ],
)
def test_database_suite_budget_cleanup_and_safe_failure(
    monkeypatch, capsys, outcome, platform, environment, timeout
):
    cleaned = []

    @contextmanager
    def isolated():
        try:
            yield SimpleNamespace(write_test_context=lambda: Path("synthetic-context"))
        finally:
            cleaned.append(True)

    def execute(arguments, **options):
        assert arguments[-3:] == ["database_tests", "--tb=short", "--maxfail=1"]
        assert options["timeout"] == timeout and options["check"] is False
        assert options["env"]["TRADING_TEST_CONTEXT"] == "synthetic-context"
        if outcome == "timeout":
            raise subprocess.TimeoutExpired("synthetic-private-command", timeout)
        return SimpleNamespace(returncode=0 if outcome == "success" else 1)

    monkeypatch.setattr(command, "disposable", isolated)
    monkeypatch.setattr(command, "os", SimpleNamespace(name=platform, environ=environment))
    monkeypatch.setattr(command.subprocess, "run", execute)
    monkeypatch.setattr(command.sys, "argv", ["trading_db", "check"])
    assert command.main() == (0 if outcome == "success" else 1)
    assert cleaned == [True]
    output = capsys.readouterr()
    assert "synthetic-private" not in output.err + output.out
    if outcome == "timeout":
        assert output.err == f"Database verification exceeded its {timeout // 60}-minute limit.\n"
