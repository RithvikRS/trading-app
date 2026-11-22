import json
import subprocess
from types import SimpleNamespace

import pytest

from trading_oracle import baseline
from trading_oracle.baseline_protocol import STAGES
from trading_oracle.local import OracleFailure


def report(*, status="passed", stage=None, completed=None, code=None):
    return {
        "version": 1,
        "status": status,
        "stage": stage or STAGES[-1],
        "completed": list(STAGES) if completed is None else completed,
        "error_code": code,
        "source_sha256": "a" * 64,
    }


@pytest.fixture
def invocation(monkeypatch, tmp_path):
    calls = []
    result = SimpleNamespace(returncode=0, stdout=json.dumps(report()), stderr="")

    def run(arguments, **options):
        calls.append((arguments, options))
        return result

    monkeypatch.setattr(baseline.subprocess, "run", run)
    monkeypatch.setattr(baseline, "digest", lambda root: "a" * 64)
    monkeypatch.setattr(baseline, "guarded", lambda path: path)
    local = SimpleNamespace(run_id="b" * 32, directory=tmp_path, port=lambda: 1521)
    return local, result, calls


def test_isolated_child_receives_only_bounded_run_descriptor(invocation, monkeypatch):
    local, result, calls = invocation
    monkeypatch.setenv("TRADING_PRIVATE_TEST_VALUE", "must-never-be-forwarded")
    monkeypatch.setenv("ORACLE_HOME", "must-never-be-forwarded")
    baseline.baseline_probe(local)
    assert len(calls) == 1
    arguments, options = calls[0]
    assert arguments[1:3] == ["-I", "-S"]
    assert json.loads(options["input"]) == {"run_id": "b" * 32, "port": 1521}
    assert "must-never-be-forwarded" not in json.dumps(options)
    assert "ORA_SDTZ" not in options["env"]
    assert options["timeout"] == 900 and options["capture_output"] is True
    assert json.loads((local.directory / "baseline-result.json").read_text()) == report()


def test_valid_failed_receipt_contains_only_fixed_stage_and_numeric_code(invocation):
    local, result, calls = invocation
    expected = report(
        status="failed", stage="migration", completed=["setup", "bootstrap"], code=942
    )
    result.returncode = 1
    result.stdout = json.dumps(expected)
    with pytest.raises(OracleFailure):
        baseline.baseline_probe(local)
    assert json.loads((local.directory / "baseline-result.json").read_text()) == expected


@pytest.mark.parametrize("fault", ["stderr", "oversize", "bad-status", "source", "duplicate"])
def test_invalid_child_result_is_never_copied_into_evidence(invocation, fault):
    local, result, calls = invocation
    marker = "do-not-copy-this-synthetic-text"
    if fault == "stderr":
        result.stderr = marker
    elif fault == "oversize":
        result.stdout = marker * 100
    elif fault == "bad-status":
        result.returncode = 1
    elif fault == "source":
        result.stdout = json.dumps({**report(), "source_sha256": marker})
    else:
        result.stdout = result.stdout[:-1] + ', "status": "' + marker + '"}'
    with pytest.raises(OracleFailure):
        baseline.baseline_probe(local)
    saved = (local.directory / "baseline-result.json").read_text()
    assert marker not in saved
    assert json.loads(saved) == report(status="failed", stage="setup", completed=[])


def test_source_change_during_child_execution_denies_success(invocation, monkeypatch):
    local, result, calls = invocation
    values = iter(["a" * 64, "c" * 64])
    monkeypatch.setattr(baseline, "digest", lambda root: next(values))
    with pytest.raises(OracleFailure):
        baseline.baseline_probe(local)
    assert json.loads((local.directory / "baseline-result.json").read_text())["status"] == "failed"


def test_timeout_is_sanitized_for_owned_finally_cleanup(invocation, monkeypatch):
    local, result, calls = invocation

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("synthetic sensitive argv", 900)

    monkeypatch.setattr(baseline.subprocess, "run", timeout)
    with pytest.raises(OracleFailure, match="^Oracle baseline probe did not complete.$"):
        baseline.baseline_probe(local)
