"""Source timestamp precision, explicit scope and stable historical canonical content."""

import json

import pytest
from pydantic import ValidationError

from trading_api.finance import FinancialInstant
from trading_db.import_contracts import BatchDefinition, CandidateDefinition, StagedValue
from trading_db.imports import canonical


def definition(**changes):
    return CandidateDefinition(
        **(
            dict(
                occurrence=1,
                kind="cash_snapshot",
                as_of_date="2026-10-24",
                snapshot_scope="native_cash",
                values=(StagedValue(role="net_cash", source="0.00", currency="INR"),),
            )
            | changes
        )
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"as_of_instant": "2026-10-24T10:00:00"},
        {"as_of_instant": "2026-10-24T10:00:00-00:00"},
        {"as_of_instant": "2026-10-24T10:00:00+14:01"},
        {"as_of_instant": "2026-10-24T24:00:00Z"},
        {"as_of_instant": "2026-10-24T10:00:60Z"},
        {"as_of_instant": "2026-10-24T10:00:00.1234567Z"},
        {"as_of_instant": "2026-10-23T10:00:00Z"},
        {"as_of_instant": "2026-10-24T10:00:00Z", "as_of_date": None},
        {"snapshot_scope": "selected_position"},
        {"snapshot_scope": "complete"},
        {"kind": "cash_movement"},
        {"kind": "lot_remaining"},
    ],
)
def test_ambiguous_or_incompatible_snapshot_metadata_is_rejected(changes):
    with pytest.raises((ValidationError, ValueError)):
        definition(**changes)


def test_date_only_and_explicit_instant_preserve_different_precision():
    day = definition(snapshot_scope=None)
    instant = definition(
        as_of_instant="2026-10-24T00:30:00.120+05:30", snapshot_scope="full_account"
    )
    assert day.as_of_instant is None and day.snapshot_scope is None
    assert day.issue() is None and instant.issue() is None
    parsed = FinancialInstant(instant.as_of_instant)
    assert parsed.to_dict() == {
        "value": "2026-10-23T19:00:00.120Z",
        "precision": "instant",
        "source_offset": "+05:30",
        "fractional_digits": 3,
    }
    assert "00:30" not in repr(instant)


def test_old_contract_hash_content_excludes_new_snapshot_metadata():
    original = BatchDefinition(
        normalizer="synthetic", normalizer_version="1", rows=(definition(snapshot_scope=None),)
    )
    revised = original.model_copy(
        update={"rows": (definition(as_of_instant="2026-10-24T10:00:00Z"),)}
    )
    for version in (1, 2, 3):
        assert canonical(original, version) == canonical(revised, version)
        row = json.loads(canonical(revised, version))["rows"][0]
        assert "as_of_instant" not in row and "snapshot_scope" not in row
    assert canonical(original, 4) != canonical(revised, 4)
