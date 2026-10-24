"""Wire evidence preserves exact source economics and rejects ambiguous inputs."""

import json
from uuid import uuid4

import pytest
from pydantic import ValidationError

from trading_api.evidence_read_contracts import (
    EventQuery,
    EventView,
    FinancialComponent,
    HistoryPage,
    HistoryQuery,
    LotObservationQuery,
    LotQuery,
)
from trading_db.evidence_reads import history_result
from trading_db.financial_reads import FinancialReadUnavailable


def record(**changes):
    return (
        dict(
            id=str(uuid4()),
            revision=1,
            is_current=True,
            source_row_id=str(uuid4()),
            source_review_revision=1,
            source_id=str(uuid4()),
            observation_id=str(uuid4()),
            batch_id=str(uuid4()),
            coverage="partial_activity",
            period_start="2026-10-01",
            period_end="2026-10-24",
            cash_date_basis=None,
            account_id=str(uuid4()),
            account_state="active",
            status="active",
            position_id=None,
            instrument_id=None,
            correction_reason=None,
            kind="cash_movement",
            posting_state="posted",
            trade_date=None,
            settlement_date=None,
            booking_date="2026-10-24",
            value_date="2026-10-23",
            components=[
                dict(role="net_cash", source="-12.30", currency="INR", missing_reason=None)
            ],
        )
        | changes
    )


@pytest.mark.parametrize("before", [True, 0, -1, 1.0, "1", 9007199254740992])
def test_history_cursor_rejects_coercion_and_unsafe_integer(before):
    with pytest.raises(ValidationError):
        HistoryQuery.model_validate({"id": str(uuid4()), "before": before})


@pytest.mark.parametrize(
    "model,field",
    [
        (EventQuery, "account_id"),
        (LotQuery, "position_id"),
        (LotObservationQuery, "lot_id"),
        (HistoryQuery, "id"),
    ],
)
def test_evidence_queries_require_explicit_canonical_parent(model, field):
    with pytest.raises(ValidationError):
        model.model_validate({})
    with pytest.raises(ValidationError):
        model.model_validate({field: str(uuid4()), "owner_id": str(uuid4())})
    with pytest.raises(ValidationError):
        model.model_validate({field: "00000000-0000-0000-0000-000000000000"})
    assert getattr(model.model_validate_json(json.dumps({field: str(uuid4())})), field)


@pytest.mark.parametrize(
    "update",
    [
        {"source": 1.23},
        {"source": True},
        {"source": "1e2"},
        {"source": "NaN"},
        {"source": "1.001"},
        {"source": "1000000000000000000"},
        {"source": None},
        {"source": "0", "missing_reason": "not_supplied"},
        {"currency": None},
        {"currency": "EUR"},
    ],
)
def test_money_rejects_float_rounding_inference_and_ambiguous_absence(update):
    with pytest.raises(ValidationError):
        FinancialComponent.model_validate(
            dict(role="net_cash", source="1.23", currency="INR", missing_reason=None) | update
        )


def test_financial_components_keep_supplied_precision_currency_and_absence():
    inputs = [
        dict(role="quantity", source="0.123456789012", currency=None, missing_reason=None),
        dict(role="net_cash", source="-999999999999999999.99", currency="USD", missing_reason=None),
        dict(role="fee", source="0.00000000", currency="USD", missing_reason=None),
        dict(
            role="reported_tax_basis",
            source=None,
            currency="INR",
            missing_reason="incomplete_history",
        ),
    ]
    for item in inputs:
        component = FinancialComponent.model_validate(item)
        assert json.loads(component.model_dump_json()) == item
        assert item["source"] is None or item["source"] not in repr(component)


@pytest.mark.parametrize(
    "update",
    [
        {"period_start": "2026-02-30"},
        {"period_start": None},
        {"period_end": "2026-09-30"},
        {"components": []},
        {"status": "cancelled"},
        {"booking_date": "2026-10-24T00:00:00Z"},
        {"revision": True},
        {"posting_state": "unknown"},
    ],
)
def test_corrupt_evidence_fails_closed_before_serialization(update):
    with pytest.raises(ValidationError):
        EventView.model_validate_json(json.dumps(record(**update)))


def test_duplicate_components_and_extra_response_fields_fail_closed():
    source = record()
    source["components"] *= 2
    with pytest.raises(ValidationError):
        EventView.model_validate_json(json.dumps(source))
    with pytest.raises(ValidationError):
        EventView.model_validate_json(json.dumps(record(encrypted_reference="synthetic")))


def test_history_pagination_preserves_full_revision_payload_and_cancellation():
    first = record(revision=3)
    middle = record(
        id=first["id"],
        revision=2,
        is_current=False,
        status="cancelled",
        components=[],
        correction_reason="cancellation",
    )
    last = record(id=first["id"], is_current=False)
    page = history_result(EventView, HistoryPage[EventView], [first, middle, last], 2)
    payload = json.loads(page.model_dump_json())
    assert payload == {"items": [first, middle], "next_before": 2}
    assert first["account_id"] not in repr(page)
    assert history_result(EventView, HistoryPage[EventView], [last], 2).next_before is None
    assert history_result(EventView, HistoryPage[EventView], [], 2).items == ()
    with pytest.raises(FinancialReadUnavailable):
        history_result(EventView, HistoryPage[EventView], [first, middle, last], 1)
    with pytest.raises(ValidationError):
        HistoryPage[EventView](items=page.items, next_before=1)
