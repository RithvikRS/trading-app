"""Inspection accepts blocked source evidence without implying successful posting."""

import json
from uuid import uuid4

import pytest
from pydantic import ValidationError

from trading_api.import_read_contracts import (
    ImportRowView,
    ReviewView,
    RowPage,
    RowQuery,
    SourceObservationView,
)


def row(**changes):
    return (
        dict(
            id=str(uuid4()),
            batch_id=str(uuid4()),
            occurrence=17,
            kind="cash_movement",
            posting_state=None,
            instrument_identifier_id=None,
            trade_date=None,
            settlement_date=None,
            booking_date="2026-10-24",
            value_date=None,
            as_of_date=None,
            acquisition_date=None,
            as_of_instant=None,
            snapshot_scope=None,
            reconciliation_boundary=None,
            blocked_reason=None,
            components=(),
            status="blocked",
            issue="not_supplied",
            decision=None,
        )
        | changes
    )


@pytest.mark.parametrize("after", [True, 0, -1, 1.5, "17", 1_000_001])
def test_occurrence_cursor_is_bounded_integer_without_coercion(after):
    with pytest.raises(ValidationError):
        RowQuery.model_validate(dict(batch_id=str(uuid4()), after_occurrence=after))


@pytest.mark.parametrize(
    "coverage,start,end",
    [
        ("complete_activity", None, None),
        ("partial_activity", "2026-10-01", None),
        ("unknown", None, "2026-10-24"),
        ("snapshot", "2026-10-24", "2026-10-01"),
        ("snapshot", "2026-02-30", "2026-10-01"),
    ],
)
def test_observation_scope_cannot_invent_or_reverse_a_period(coverage, start, end):
    with pytest.raises(ValidationError):
        SourceObservationView.model_validate(
            dict(
                id=str(uuid4()),
                source_id=str(uuid4()),
                previous_id=None,
                is_current=True,
                coverage=coverage,
                period_start=start,
                period_end=end,
            )
        )


def test_unknown_period_remains_inspectable_without_inventing_dates():
    result = SourceObservationView.model_validate(
        dict(
            id=str(uuid4()),
            source_id=str(uuid4()),
            previous_id=None,
            is_current=True,
            coverage="unknown",
            period_start=None,
            period_end=None,
        )
    )
    assert json.loads(result.model_dump_json())["period_start"] is None


def test_missing_components_and_posting_state_stay_blocked_source_evidence():
    result = ImportRowView.model_validate(row())
    assert (
        result.components == () and result.posting_state is None and result.issue == "not_supplied"
    )
    assert result.model_dump()["status"] == "blocked"
    page = RowPage(items=(result,), next_after_occurrence=17)
    assert page.model_dump()["next_after_occurrence"] == 17
    with pytest.raises(ValidationError):
        RowPage(items=(result,), next_after_occurrence=18)


def test_reported_cash_and_missing_fee_roundtrip_without_float_or_zero_inference():
    values = (
        dict(role="net_cash", source="-12.30", currency="INR", missing_reason=None),
        dict(role="fee", source=None, currency="INR", missing_reason="not_supplied"),
    )
    result = ImportRowView.model_validate(
        row(components=values, posting_state="pending", status="reviewable", issue=None)
    )
    assert json.loads(result.model_dump_json())["components"] == list(values)
    with pytest.raises(ValidationError):
        ImportRowView.model_validate(row(components=values + (values[0],)))
    with pytest.raises(ValidationError):
        ImportRowView.model_validate(row(components=(values[0] | {"source": -12.3},)))


def review(**changes):
    return (
        dict(
            id=str(uuid4()),
            revision=1,
            is_current=True,
            action="include",
            reason="reviewed",
            source_id=str(uuid4()),
            account_mapping_revision=1,
            instrument_identifier_id=None,
            instrument_mapping_revision=None,
        )
        | changes
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"account_mapping_revision": None},
        {"reason": "user_excluded"},
        {"instrument_identifier_id": str(uuid4())},
        {"instrument_mapping_revision": 1},
        {"action": "exclude", "reason": "user_excluded"},
        {"action": "reopen", "reason": "reopened"},
    ],
)
def test_saved_review_intent_requires_its_original_mapping_context(changes):
    with pytest.raises(ValidationError):
        ReviewView.model_validate(review(**changes))


def test_row_current_decision_cannot_point_to_another_row_or_historical_revision():
    own = row()
    decision = review(id=own["id"])
    assert ImportRowView.model_validate(own | {"decision": decision}).decision.id == own["id"]
    for change in ({"id": str(uuid4())}, {"is_current": False}):
        with pytest.raises(ValidationError):
            ImportRowView.model_validate(own | {"decision": decision | change})
