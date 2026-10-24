"""Reported market values and source timestamps retain their original meaning."""

import json
from uuid import uuid4

import pytest
from pydantic import ValidationError

from trading_api.valuation_read_contracts import (
    MarketObservationView,
    MarketQuery,
    MarketResolution,
    SnapshotResolution,
)


def quote(**changes):
    return (
        dict(
            id=str(uuid4()),
            previous_id=None,
            is_current=True,
            kind="quote",
            instrument_id=str(uuid4()),
            listing_id=str(uuid4()),
            currency="USD",
            base_currency=None,
            quote_currency=None,
            basis="close",
            adjustment="unadjusted",
            namespace="exchange_quote_report",
            observed_on="2026-10-24",
            observed_at="2026-10-24T00:30:00.120+05:30",
            source="325.123456789012",
            missing_reason=None,
            usable=True,
        )
        | changes
    )


@pytest.mark.parametrize(
    "source,reason", [("0.000", None), ("-1.123456789012", None), (None, "not_supplied")]
)
def test_reported_nonpositive_or_missing_price_is_inspectable_without_becoming_usable(
    source, reason
):
    raw = quote(source=source, missing_reason=reason, usable=False)
    result = MarketObservationView.model_validate(raw)
    assert json.loads(result.model_dump_json()) == raw
    assert source is None or source not in repr(result)
    with pytest.raises(ValidationError):
        MarketObservationView.model_validate(raw | {"usable": True})


@pytest.mark.parametrize("adjustment", ["split_adjusted", "unknown"])
def test_adjusted_quotes_cannot_claim_usable_even_when_positive(adjustment):
    raw = quote(adjustment=adjustment, usable=False)
    assert not MarketObservationView.model_validate(raw).usable
    with pytest.raises(ValidationError):
        MarketObservationView.model_validate(raw | {"usable": True})


def test_date_only_observation_and_source_local_timestamp_stay_distinct():
    raw = quote()
    result = MarketObservationView.model_validate(raw)
    assert result.observed_at == "2026-10-24T00:30:00.120+05:30"
    assert result.observed_on == "2026-10-24"
    assert MarketObservationView.model_validate(quote(observed_at=None)).observed_at is None
    with pytest.raises(ValidationError):
        MarketObservationView.model_validate(quote(observed_on="2026-10-23"))


@pytest.mark.parametrize(
    "update",
    [
        {"source": 1.25},
        {"source": "NaN"},
        {"source": "1e3"},
        {"source": "1.0000000000001"},
        {"currency": None},
        {"adjustment": None},
        {"observed_at": "2026-10-24T00:30:00"},
        {"observed_at": "2026-10-24T00:30:00-00:00"},
        {"observed_on": "2026-02-30"},
        {"digest": "synthetic"},
    ],
)
def test_corrupt_or_overbroad_market_projection_fails_closed(update):
    with pytest.raises(ValidationError):
        MarketObservationView.model_validate(quote(**update))


@pytest.mark.parametrize(
    "body",
    [
        {"kind": "fx", "instrument_id": str(uuid4())},
        {"kind": "quote"},
        {"kind": "nav"},
        {"kind": "other"},
        {"kind": "fx", "limit": True},
        {"kind": "fx", "quote_currency": "USD"},
        {"kind": "fx", "owner_id": str(uuid4())},
    ],
)
def test_market_queries_never_infer_instrument_or_accept_extra_scope(body):
    with pytest.raises(ValidationError):
        MarketQuery.model_validate(body)


def test_directed_fx_roundtrips_without_inversion_or_price_adjustment():
    raw = quote(
        kind="fx",
        instrument_id=None,
        listing_id=None,
        currency=None,
        base_currency="USD",
        quote_currency="INR",
        basis="reference",
        adjustment=None,
        namespace="fx_rate_report",
        source="83.123456789012",
    )
    result = MarketObservationView.model_validate(raw)
    assert json.loads(result.model_dump_json()) == raw
    with pytest.raises(ValidationError):
        MarketObservationView.model_validate(raw | {"quote_currency": "USD"})


@pytest.mark.parametrize("state", ["unselected", "stale", "unusable"])
def test_unavailable_market_resolution_cannot_attach_a_price(state):
    observation = MarketObservationView.model_validate(quote())
    selection = observation.model_dump(
        include={
            "kind",
            "instrument_id",
            "listing_id",
            "currency",
            "base_currency",
            "quote_currency",
            "basis",
        }
    ) | dict(
        id=str(uuid4()),
        revision=1,
        is_current=True,
        observation_id=observation.id,
        reason="reviewed",
    )
    with pytest.raises(ValidationError):
        MarketResolution.model_validate(
            dict(selection=selection, state=state, observation=observation)
        )
    assert (
        MarketResolution.model_validate(
            dict(selection=selection, state="stale", observation=None)
        ).observation
        is None
    )


def test_selected_snapshot_cannot_omit_the_validated_snapshot_payload():
    selection = dict(
        id=str(uuid4()),
        revision=1,
        is_current=True,
        account_id=str(uuid4()),
        position_id=None,
        currency="INR",
        snapshot_id=str(uuid4()),
        snapshot_revision=1,
        reason="reviewed",
    )
    with pytest.raises(ValidationError):
        SnapshotResolution.model_validate(
            dict(selection=selection, state="selected", snapshot=None)
        )
