"""Independent normalized evidence examples, unknown values and source precision."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from trading_db.import_contracts import (
    EVENT_KINDS,
    BatchDefinition,
    CandidateDefinition,
    ObservationDefinition,
    StagedValue,
)
from trading_db.imports import canonical


def cash(source="-12.30", **changes):
    return StagedValue(**(dict(role="net_cash", source=source, currency="INR") | changes))


def candidate(**changes):
    changes.setdefault(
        "posting_state", "posted" if changes.get("kind", "cash_movement") in EVENT_KINDS else None
    )
    return CandidateDefinition(
        **(
            dict(occurrence=1, kind="cash_movement", booking_date="2026-10-24", values=(cash(),))
            | changes
        )
    )


@pytest.mark.parametrize(
    "source",
    [
        12.30,
        12,
        True,
        "1e2",
        "NaN",
        "Infinity",
        " 1",
        "+1",
        "01",
        "1.001",
        "1,000",
        "1\n",
        "９",
        "1" * 19,
    ],
)
def test_invalid_cash_does_not_get_coerced_or_rounded(source):
    with pytest.raises(ValidationError):
        cash(source)


def test_zero_unknown_and_original_precision_remain_distinct():
    zero = cash("-0.00")
    unknown = cash(None, missing_reason="not_supplied")
    assert zero.source == "-0.00" and zero.financial().to_dict()["value"] == "0.00"
    assert unknown.financial().value is None
    assert candidate(values=(zero,)).issue() is None
    assert candidate(values=(unknown,)).issue() == "not_supplied"
    assert "-0.00" not in repr(zero) and "2026-10-24" not in repr(candidate())


@pytest.mark.parametrize(
    "changes",
    [
        {"currency": None},
        {"missing_reason": "not_supplied"},
        {"owner_id": uuid4()},
        {"role": "raw_payload"},
        {"source": None},
    ],
)
def test_unsupported_value_context_fails(changes):
    with pytest.raises(ValidationError):
        cash(**changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"period_start": "2026-02-30", "period_end": "2026-03-01"},
        {"period_start": "2026-10-24", "period_end": "2026-10-01"},
        {"period_start": "2026-10-01", "period_end": None},
        {"digest": "a" * 63},
        {"digest": "A" * 64},
        {"digest_algorithm": "md5"},
        {"coverage": "complete_activity"},
        {"filename": "private-statement.csv"},
    ],
)
def test_observation_requires_exact_digest_and_explicit_period(changes):
    with pytest.raises(ValidationError):
        ObservationDefinition(**(dict(digest="a" * 64, coverage="unknown") | changes))


@pytest.mark.parametrize(
    "kind,quantity,net,issue",
    [
        ("buy", "1.000000000001", "-12.30", None),
        ("sell", "-1.2", "12.30", None),
        ("subscription", "1", "-10", None),
        ("redemption", "-1", "10", None),
        ("buy", "-1", "-12.30", "conflicting_evidence"),
        ("sell", "-1", "-12.30", "conflicting_evidence"),
        ("buy", "0", "0", "conflicting_evidence"),
    ],
)
def test_signed_trade_components_are_not_inferred(kind, quantity, net, issue):
    row = candidate(
        kind=kind,
        trade_date="2026-10-24",
        instrument_identifier_id=uuid4(),
        values=(StagedValue(role="quantity", source=quantity), cash(net)),
    )
    assert row.issue() == issue


def test_missing_basis_does_not_become_zero_or_block_known_lot_evidence():
    row = candidate(
        kind="lot_remaining",
        as_of_date="2026-10-24",
        instrument_identifier_id=uuid4(),
        values=(
            StagedValue(role="quantity", source="0.123456789012"),
            StagedValue(
                role="reported_tax_basis",
                source=None,
                currency="USD",
                missing_reason="incomplete_history",
            ),
        ),
    )
    assert row.issue() is None
    assert row.values[1].financial().value is None


def test_occurrences_keep_legitimate_identical_rows_and_component_order_is_canonical():
    first = candidate(values=(cash(), StagedValue(role="fee", source="0.00", currency="INR")))
    second = first.model_copy(update={"occurrence": 2})
    batch = BatchDefinition(normalizer="synthetic", normalizer_version="1", rows=(first, second))
    reversed_values = batch.model_copy(
        update={
            "rows": tuple(
                row.model_copy(update={"values": tuple(reversed(row.values))}) for row in batch.rows
            )
        }
    )
    assert canonical(batch) == canonical(reversed_values)
    with pytest.raises(ValidationError):
        BatchDefinition(normalizer="synthetic", normalizer_version="1", rows=(first, first))
    with pytest.raises(ValidationError):
        CandidateDefinition.model_validate(
            first.model_copy(update={"values": (cash(), cash())}).model_dump()
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"booking_date": "2026-10-24T00:00:00Z"},
        {"occurrence": True},
        {"occurrence": 0},
        {"instrument_identifier_id": "not-a-uuid"},
        {"raw_description": "private"},
    ],
)
def test_row_rejects_ambiguous_dates_and_unbounded_source_fields(changes):
    with pytest.raises(ValidationError):
        candidate(**changes)


def test_posting_evidence_is_explicit_and_legacy_digest_is_versioned():
    unknown = candidate(posting_state=None)
    pending = candidate(posting_state="pending")
    posted = candidate(posting_state="posted")
    assert unknown.issue() == "not_supplied"
    assert pending.issue() is posted.issue() is None
    batches = [
        BatchDefinition(normalizer="synthetic", normalizer_version="1", rows=(row,))
        for row in (unknown, pending, posted)
    ]
    assert len({canonical(value) for value in batches}) == 3
    assert len({canonical(value, 1) for value in batches}) == 1
    with pytest.raises(ValidationError):
        candidate(kind="cash_snapshot", posting_state="posted")
