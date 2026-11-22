import json

import pytest

from trading_oracle.baseline_protocol import STAGES, parse

SOURCE = "a" * 64


def report():
    return {
        "version": 1,
        "status": "passed",
        "stage": STAGES[-1],
        "completed": list(STAGES),
        "error_code": None,
        "source_sha256": SOURCE,
    }


def test_pass_requires_complete_ordered_source_bound_result():
    value = report()
    assert parse(json.dumps(value), SOURCE) == value
    with pytest.raises(ValueError):
        parse(json.dumps(value), "b" * 64)


@pytest.mark.parametrize(
    "field,value",
    [
        ("version", True),
        ("version", 1.0),
        ("version", "1"),
        ("status", "unknown"),
        ("completed", []),
        ("completed", ["bootstrap", "setup"]),
        ("completed", list(STAGES) + [STAGES[-1]]),
        ("stage", "unknown"),
        ("error_code", 1),
        ("error_code", True),
        ("source_sha256", "b" * 64),
    ],
)
def test_rejects_malformed_or_premature_pass(field, value):
    document = report()
    document[field] = value
    with pytest.raises(ValueError):
        parse(json.dumps(document), SOURCE)


@pytest.mark.parametrize("position", range(len(STAGES)))
def test_failed_result_identifies_only_the_next_fixed_stage(position):
    document = report()
    document.update(
        status="failed", completed=list(STAGES[:position]), stage=STAGES[position], error_code=942
    )
    assert parse(json.dumps(document), SOURCE) == document


@pytest.mark.parametrize("code", [True, -1, 65536, "942", 942.0])
def test_failure_diagnostic_never_accepts_text_or_coerced_numbers(code):
    document = report()
    document.update(status="failed", completed=[], stage="setup", error_code=code)
    with pytest.raises(ValueError):
        parse(json.dumps(document), SOURCE)


def test_duplicates_unknown_fields_and_oversize_results_are_denied():
    raw = json.dumps(report())
    with pytest.raises(ValueError):
        parse(raw[:-1] + ', "version": 1}', SOURCE)
    with pytest.raises(ValueError):
        parse(json.dumps({**report(), "raw_driver_message": "unused synthetic diagnostic"}), SOURCE)
    with pytest.raises(ValueError):
        parse(" " * 2049, SOURCE)
