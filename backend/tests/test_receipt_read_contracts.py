"""Frozen comparisons preserve exact strings and explicit completion meaning."""

import json
from uuid import uuid4

import pytest
from pydantic import ValidationError

from trading_api.receipt_read_contracts import (
    ComparisonInputView,
    CompletedRowView,
    InputQuery,
    ReceiptView,
    ScopeInspection,
)


def identifier():
    return str(uuid4())


def receipt(**changes):
    return (
        dict(
            id=identifier(),
            batch_id=identifier(),
            batch_revision=1,
            mode="reconciled",
            coverage="complete_activity",
            created_at="2026-10-24T12:00:00.000001+00:00",
            row_count=3,
            selection_count=0,
            scope_count=1,
        )
        | changes
    )


def effect(**changes):
    return (
        dict(
            id=identifier(),
            receipt_id=identifier(),
            review_revision=1,
            operation="record",
            outcome="recorded",
            event_id=identifier(),
            lot_observation_id=None,
            snapshot_id=None,
            record_revision=1,
            provider_identity_id=None,
            selection_id=None,
            selection_revision=None,
        )
        | changes
    )


def comparison():
    side = dict(
        outcome="balanced",
        opening="100.000000000001",
        closing="87.700000000002",
        posted_total="-12.299999999999",
        calculated_closing="87.700000000002",
        difference="0.000000000000",
        posted_count=1,
        pending_count=0,
    )
    return dict(
        scope=dict(
            id=identifier(),
            receipt_id=identifier(),
            kind="units",
            account_id=identifier(),
            position_id=identifier(),
            currency=None,
            period_start="2026-10-01",
            period_end="2026-10-24",
            date_basis="trade",
            rule_version=1,
            input_count=6,
        ),
        source=dict(side),
        combined=dict(side),
    )


def frozen_input(**changes):
    reference = identifier()
    return (
        dict(
            id=reference,
            scope_id=identifier(),
            side="combined",
            part="activity",
            reference_revision=2,
            source_row_id=None,
            event_id=reference,
            snapshot_id=None,
            source="-12.300000000001",
            evidence_date="2026-10-24",
            posting_state="posted",
            kind="units",
            currency=None,
        )
        | changes
    )


def test_exact_frozen_units_and_utc_completion_timestamp_roundtrip():
    raw = comparison()
    assert json.loads(ScopeInspection.model_validate(raw).model_dump_json()) == raw
    saved = receipt()
    assert json.loads(ReceiptView.model_validate(saved).model_dump_json()) == saved
    inputs = frozen_input()
    assert json.loads(ComparisonInputView.model_validate(inputs).model_dump_json()) == inputs
    assert inputs["source"] not in repr(ComparisonInputView.model_validate(inputs))


@pytest.mark.parametrize(
    "changes",
    [
        dict(mode="limited"),
        dict(scope_count=0),
        dict(scope_count=101),
        dict(coverage="unknown"),
        dict(row_count=0),
        dict(idempotency_key=identifier()),
        dict(created_at="2026-10-24T12:00:00"),
        dict(row_count=True),
    ],
)
def test_receipt_requires_consistent_coverage_and_bounded_public_fields(changes):
    with pytest.raises(ValidationError):
        ReceiptView.model_validate(receipt(**changes))


@pytest.mark.parametrize(
    "changes",
    [
        dict(operation="exclude"),
        dict(outcome="excluded"),
        dict(outcome="corrected"),
        dict(lot_observation_id=identifier()),
        dict(record_revision=None),
        dict(selection_id=identifier(), selection_revision=1),
        dict(selection_revision=1),
    ],
)
def test_completed_effect_cannot_invent_another_target_or_attach_selection(changes):
    with pytest.raises(ValidationError):
        CompletedRowView.model_validate(effect(**changes))


def test_exclusion_has_no_financial_target_and_correction_retains_revision():
    assert (
        CompletedRowView.model_validate(
            effect(operation="exclude", outcome="excluded", event_id=None, record_revision=None)
        ).event_id
        is None
    )
    corrected = CompletedRowView.model_validate(
        effect(operation="correct", outcome="corrected", record_revision=3)
    )
    assert corrected.record_revision == 3


@pytest.mark.parametrize(
    "field,value",
    [
        ("posted_total", "-12.300000000000"),
        ("opening", "100.000000000002"),
        ("difference", "0.01"),
        ("calculated_closing", "87.70"),
        ("posted_total", "1e3"),
        ("posted_total", "NaN"),
        ("posted_total", "10000000000000000000000"),
        ("posted_total", "-12.2999999999990"),
        ("posted_total", -12.3),
    ],
)
def test_balanced_label_cannot_hide_a_wrong_or_inexact_equation(field, value):
    raw = comparison()
    raw["source"][field] = value
    with pytest.raises(ValidationError):
        ScopeInspection.model_validate(raw)


@pytest.mark.parametrize(
    "changes",
    [
        dict(source=12.3),
        dict(source="1e2"),
        dict(kind="cash", currency=None),
        dict(side="source"),
        dict(source_row_id=identifier()),
        dict(event_id=identifier()),
        dict(posting_state=None),
        dict(part="closing"),
        dict(currency="USD"),
    ],
)
def test_frozen_input_requires_exact_value_and_unambiguous_lineage(changes):
    with pytest.raises(ValidationError):
        ComparisonInputView.model_validate(frozen_input(**changes))


@pytest.mark.parametrize(
    "changes",
    [
        dict(side=None),
        dict(part="all"),
        dict(limit=101),
        dict(after=identifier().upper()),
        dict(limit=True),
    ],
)
def test_input_page_requires_explicit_side_part_and_strict_cursor(changes):
    with pytest.raises(ValidationError):
        InputQuery.model_validate(
            dict(scope_id=identifier(), side="source", part="activity") | changes
        )
