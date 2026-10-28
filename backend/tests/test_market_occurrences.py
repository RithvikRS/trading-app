"""Synthetic source positions expand only through explicit AMFI NAV contract v2."""

from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest
from pydantic import ValidationError

from tests.test_amfi import OTHER, report, row
from trading_api.amfi import NavTarget, match_nav, parse_report
from trading_db.market_contracts import MarketDefinition, validate_market_occurrence

SCOPES = (
    ("quote", "manual_evidence"),
    ("quote", "exchange_quote_report"),
    ("nav", "manual_evidence"),
    ("nav", "amfi_nav_report"),
    ("fx", "manual_evidence"),
    ("fx", "fx_rate_report"),
)
INSTRUMENT = UUID("70000000-0000-4000-8000-000000000001")
LISTING = UUID("70000000-0000-4000-8000-000000000002")


def payload(kind="nav", namespace="amfi_nav_report", **changes):
    target = (
        dict(base_currency="USD", quote_currency="INR", basis="reference")
        if kind == "fx"
        else dict(instrument_id=INSTRUMENT, currency="INR", basis="nav")
    )
    if kind == "quote":
        target |= dict(listing_id=LISTING, basis="close", adjustment="unadjusted")
    return (
        dict(
            kind=kind,
            namespace=namespace,
            digest="a" * 64,
            occurrence=1,
            normalizer="synthetic",
            normalizer_version=1,
            observed_on="2026-10-23",
            source="12.340000000001",
        )
        | target
        | changes
    )


@pytest.mark.parametrize("kind,namespace", SCOPES)
@pytest.mark.parametrize("occurrence", [1, 1000])
def test_legacy_default_preserves_all_existing_source_domains(kind, namespace, occurrence):
    data = payload(kind, namespace, occurrence=occurrence)
    value = MarketDefinition.model_validate(data)
    explicit = MarketDefinition.model_validate(data | {"contract_version": 1})
    assert value == explicit and value.contract_version == 1
    assert value.occurrence == occurrence
    assert MarketDefinition.model_validate_json(value.model_dump_json()) == value
    assert value.reported().value == Decimal("12.340000000001")


@pytest.mark.parametrize("kind,namespace", SCOPES)
@pytest.mark.parametrize("occurrence", [1001, 25000, 25001])
def test_legacy_version_never_inherits_the_larger_ordinal_bound(kind, namespace, occurrence):
    with pytest.raises(ValidationError):
        MarketDefinition.model_validate(payload(kind, namespace, occurrence=occurrence))


@pytest.mark.parametrize("occurrence", [1, 1000, 1001, 25000])
def test_explicit_amfi_v2_retains_original_position_and_exact_source(occurrence):
    value = MarketDefinition.model_validate(payload(occurrence=occurrence, contract_version=2))
    assert value.contract_version == 2 and value.occurrence == occurrence
    assert value.source == "12.340000000001" and value.observed_on == "2026-10-23"
    assert value.reported().value == Decimal("12.340000000001")
    assert value.usable and value.listing_id is None
    assert value.target().instrument_id == INSTRUMENT
    assert MarketDefinition.model_validate_json(value.model_dump_json()) == value
    assert value.source not in repr(value) + repr(value.reported())
    assert value.digest not in repr(value)


@pytest.mark.parametrize(
    "kind,namespace", [scope for scope in SCOPES if scope[1] != "amfi_nav_report"]
)
@pytest.mark.parametrize("occurrence", [1, 1001])
def test_other_sources_cannot_opt_into_version_two_even_at_low_positions(
    kind, namespace, occurrence
):
    with pytest.raises(ValidationError):
        MarketDefinition.model_validate(
            payload(kind, namespace, occurrence=occurrence, contract_version=2)
        )


@pytest.mark.parametrize("version", [True, False, 1.0, 2.0, "1", "2", None, 0, 3])
def test_version_is_an_explicit_supported_integer(version):
    with pytest.raises(ValidationError):
        MarketDefinition.model_validate(payload(contract_version=version))


@pytest.mark.parametrize("version", [1, 2])
@pytest.mark.parametrize(
    "occurrence", [True, False, 1.0, 25000.0, "1", "25000", None, 0, -1, 25001]
)
def test_source_position_rejects_coercion_and_out_of_range_values(version, occurrence):
    with pytest.raises(ValidationError):
        MarketDefinition.model_validate(payload(contract_version=version, occurrence=occurrence))


@pytest.mark.parametrize(
    "changes",
    [
        dict(kind=True),
        dict(kind=["nav"]),
        dict(namespace=True),
        dict(namespace=["amfi_nav_report"]),
        dict(namespace="manual_evidence"),
        dict(kind="quote", namespace="exchange_quote_report"),
        dict(kind="fx", namespace="fx_rate_report"),
        dict(contract_version=True),
        dict(contract_version="2"),
        dict(contract_version=2.0),
        dict(contract_version=3),
        dict(occurrence=True),
        dict(occurrence="25000"),
        dict(occurrence=25000.0),
        dict(occurrence=25001),
    ],
)
def test_pre_storage_guard_rejects_types_and_domains_before_sql_can_coerce_them(changes):
    values = dict(kind="nav", namespace="amfi_nav_report", contract_version=2, occurrence=25000)
    with pytest.raises(ValueError, match="^Market source occurrence is unsupported\\.$"):
        validate_market_occurrence(**(values | changes))


@pytest.mark.parametrize("kind,namespace", SCOPES)
def test_pre_storage_guard_preserves_legacy_scope_and_position_rules(kind, namespace):
    validate_market_occurrence(kind, namespace, 1, 1000)
    with pytest.raises(ValueError):
        validate_market_occurrence(kind, namespace, 1, 1001)


@pytest.mark.parametrize("occurrence", [1, 1000, 1001, 25000])
def test_pre_storage_guard_accepts_the_explicit_amfi_version_domain(occurrence):
    validate_market_occurrence("nav", "amfi_nav_report", 2, occurrence)


@pytest.mark.parametrize(
    "source,missing,usable",
    [
        (None, "not_supplied", False),
        ("0", None, False),
        ("-0.0000", None, False),
        ("-1.000000000001", None, False),
        ("12.340000000001", None, True),
    ],
)
def test_high_position_keeps_missing_nonpositive_and_exact_value_meanings(source, missing, usable):
    value = MarketDefinition.model_validate(
        payload(contract_version=2, occurrence=25000, source=source, missing_reason=missing)
    )
    assert value.source == source and value.missing_reason == missing
    assert value.usable is usable
    if source is None:
        assert value.reported().value is None
    else:
        assert value.reported().value == Decimal(source)


@pytest.mark.parametrize(
    "changes",
    [
        dict(source="1e2"),
        dict(source="1.1234567890123"),
        dict(currency="USD"),
        dict(listing_id=LISTING),
        dict(observed_at="2026-10-24T00:00:00Z"),
        dict(missing_reason="not_supplied"),
        dict(unexpected=True),
    ],
)
def test_new_version_does_not_weaken_existing_value_date_or_target_contracts(changes):
    with pytest.raises(ValueError):
        MarketDefinition.model_validate(payload(contract_version=2, occurrence=25000) | changes)


def test_selected_fabricated_report_row_above_legacy_bound_is_not_renumbered():
    raw = report(*(row() for _ in range(1000)), row(code="900003", first=OTHER))
    parsed = parse_report(raw)
    matched = match_nav(
        parsed,
        NavTarget(scheme_code="900003", isin=OTHER, plan="direct", option="growth"),
        as_of=date(2026, 10, 23),
        max_age_days=0,
    )
    selected = matched.usable
    assert selected is not None and selected.occurrence == 1001
    assert selected.line_number > selected.occurrence
    definition = payload(
        digest=parsed.digest,
        occurrence=selected.occurrence,
        observed_on=selected.observed_on.isoformat(),
        source=selected.nav_source,
    )
    with pytest.raises(ValidationError):
        MarketDefinition.model_validate(definition)
    retained = MarketDefinition.model_validate(definition | {"contract_version": 2})
    assert retained.occurrence == 1001 and retained.digest == parsed.digest
    assert retained.source == selected.nav_source
    assert retained.observed_on == selected.observed_on.isoformat()
