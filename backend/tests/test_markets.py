"""Reported source values remain exact without weakening usable price contracts."""

from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from trading_api.finance import FinancialValue, FinancialValueError, ReportedMarketValue
from trading_db.market_contracts import MarketDefinition


def definition(**changes):
    return MarketDefinition.model_validate(
        dict(
            kind="fx",
            base_currency="USD",
            quote_currency="INR",
            basis="reference",
            namespace="manual_evidence",
            digest="a" * 64,
            occurrence=1,
            normalizer="synthetic",
            normalizer_version=1,
            observed_on="2026-10-24",
            source="83.123456789012",
        )
        | changes
    )


@pytest.mark.parametrize("source", ["0", "-0.000", "-1.123456789012"])
def test_nonpositive_reported_values_are_retained_but_cannot_be_used(source):
    reported = ReportedMarketValue("unit_price", source, currency="USD")
    assert reported.source == source and reported.value == Decimal(source)
    assert not reported.usable
    with pytest.raises(FinancialValueError):
        reported.financial()
    with pytest.raises(FinancialValueError):
        FinancialValue("unit_price", source, currency="USD")


def test_exact_directed_rate_precision_missing_and_private_representation():
    evidence = definition(observed_at="2026-10-24T00:30:00.120+05:30")
    price = evidence.reported().financial()
    assert price.value == Decimal("83.123456789012")
    assert price.base_currency == "USD" and price.quote_currency == "INR"
    assert evidence.observed_at.endswith(".120+05:30")
    assert "83.123456789012" not in repr(evidence) + repr(evidence.reported())
    missing = definition(source=None, missing_reason="not_supplied")
    assert missing.reported().value is None and not missing.usable


@pytest.mark.parametrize(
    "changes",
    [
        dict(source=1.5),
        dict(source=True),
        dict(source="NaN"),
        dict(source="1e2"),
        dict(source="01"),
        dict(source="1.0000000000001"),
        dict(source="1000000000000000000"),
        dict(source=None),
        dict(source="1", missing_reason="not_supplied"),
        dict(source=" 1"),
        dict(base_currency="USD", quote_currency="USD"),
        dict(currency="USD"),
        dict(instrument_id=uuid4()),
        dict(observed_on="2026-02-30"),
        dict(observed_at="2026-10-24T00:30:00"),
        dict(observed_at="2026-10-25T00:30:00Z"),
        dict(adjustment="unadjusted"),
        dict(namespace="amfi_nav_report"),
        dict(previous_id=uuid4().hex),
        dict(previous_id=UUID(int=0)),
        dict(occurrence=True),
        dict(occurrence=1001),
        dict(normalizer="bad/provider"),
        dict(normalizer_version=0),
        dict(digest="A" * 64),
        dict(contract_version=2),
        dict(contract_version=True),
    ],
)
def test_contract_rejects_ambiguous_or_unbounded_evidence(changes):
    with pytest.raises((ValidationError, FinancialValueError)):
        definition(**changes)


def test_quote_and_nav_identity_adjustment_and_currency():
    quote = definition(
        kind="quote",
        instrument_id=uuid4(),
        listing_id=uuid4(),
        currency="USD",
        base_currency=None,
        quote_currency=None,
        basis="close",
        adjustment="unknown",
    )
    assert not quote.usable
    changed = MarketDefinition.model_validate(quote.model_dump() | {"adjustment": "unadjusted"})
    assert changed.usable
    with pytest.raises(ValidationError):
        MarketDefinition.model_validate(quote.model_dump() | {"listing_id": None})
    nav = definition(
        kind="nav",
        instrument_id=uuid4(),
        currency="INR",
        base_currency=None,
        quote_currency=None,
        basis="nav",
        namespace="amfi_nav_report",
    )
    assert nav.usable and nav.listing_id is None
    with pytest.raises(ValidationError):
        MarketDefinition.model_validate(nav.model_dump() | {"currency": "USD"})
