"""A bounded database suite still cleans up and fails without exposing diagnostics."""

import subprocess
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from trading_db import __main__ as command


@pytest.mark.parametrize("outcome", ["success", "failed", "timeout"])
def test_database_suite_budget_cleanup_and_safe_failure(monkeypatch, capsys, outcome):
    cleaned = []

    @contextmanager
    def isolated():
        try:
            yield SimpleNamespace(write_test_context=lambda: Path("synthetic-context"))
        finally:
            cleaned.append(True)

    def execute(arguments, **options):
        assert arguments[-3:] == ["database_tests", "--tb=short", "--maxfail=1"]
        assert options["timeout"] == 900 and options["check"] is False
        assert options["env"]["TRADING_TEST_CONTEXT"] == "synthetic-context"
        if outcome == "timeout":
            raise subprocess.TimeoutExpired("synthetic-private-command", 900)
        return SimpleNamespace(returncode=0 if outcome == "success" else 1)

    monkeypatch.setattr(command, "disposable", isolated)
    monkeypatch.setattr(command.subprocess, "run", execute)
    monkeypatch.setattr(command.sys, "argv", ["trading_db", "check"])
    assert command.main() == (0 if outcome == "success" else 1)
    assert cleaned == [True]
    output = capsys.readouterr()
    assert "synthetic-private" not in output.err + output.out
    if outcome == "timeout":
        assert output.err == "Database verification exceeded its 15-minute limit.\n"
