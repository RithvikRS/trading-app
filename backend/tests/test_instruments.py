"""Synthetic security identity contracts, independently checked standard identifiers."""

from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from trading_db.instruments import (
    IdentifierDefinition,
    InstrumentDefinition,
    InstrumentUnavailable,
    ListingDefinition,
    SchemeDefinition,
    validate_isin,
)

# Public checksum examples; these tests do not represent personal holdings.
ISINS = ("INE475C01012", "US0378331005", "IE00B4BNMY34", "US5949181045")


@pytest.mark.parametrize("value", ISINS)
def test_known_check_digits_preserve_exact_identifier(value):
    assert validate_isin(value) == value
    for offset in range(1, 10):
        changed = value[:-1] + str((int(value[-1]) + offset) % 10)
        with pytest.raises(InstrumentUnavailable):
            validate_isin(changed)


@pytest.mark.parametrize(
    "value",
    [
        None,
        123456789012,
        True,
        "",
        "US037833100",
        "US03783310055",
        "us0378331005",
        "US0378331005\n",
        " US0378331005",
        "UＳ0378331005",
        "US037833100A",
    ],
)
def test_invalid_isin_is_not_coerced_or_normalized(value):
    with pytest.raises(InstrumentUnavailable):
        validate_isin(value)


def test_fund_variants_require_explicit_plan_option_currency_and_opaque_scheme():
    scheme = uuid4()
    for plan in ("direct", "regular"):
        for option in ("growth", "idcw_payout", "idcw_reinvestment"):
            value = InstrumentDefinition(
                name="Synthetic Fund",
                asset_class="mutual_fund",
                isin=ISINS[0],
                fund_scheme_id=scheme,
                fund_plan=plan,
                fund_option=option,
                fund_currency="INR",
            )
            assert value.fund_option == option and value.fund_scheme_id == scheme


@pytest.mark.parametrize(
    "changes",
    [
        {"fund_scheme_id": None},
        {"fund_scheme_id": UUID(int=0)},
        {"fund_scheme_id": "not-a-uuid"},
        {"fund_plan": None},
        {"fund_plan": "unknown"},
        {"fund_option": None},
        {"fund_option": "dividend"},
        {"fund_currency": None},
        {"fund_currency": "USD"},
        {"owner_id": uuid4()},
        {"isin": ""},
        {"name": "<script>"},
        {"name": "x\n"},
    ],
)
def test_partial_fund_definition_remains_unsupported(changes):
    values = dict(
        name="Synthetic Fund",
        asset_class="mutual_fund",
        isin=ISINS[0],
        fund_scheme_id=uuid4(),
        fund_plan="regular",
        fund_option="growth",
        fund_currency="INR",
    )
    with pytest.raises(ValidationError):
        InstrumentDefinition(**(values | changes))


@pytest.mark.parametrize(
    "field,value",
    [
        ("fund_scheme_id", uuid4()),
        ("fund_plan", "direct"),
        ("fund_option", "growth"),
        ("fund_currency", "INR"),
    ],
)
def test_equity_and_etf_do_not_accept_fund_variant_fields(field, value):
    for kind in ("equity", "etf"):
        with pytest.raises(ValidationError):
            InstrumentDefinition(
                name="Synthetic security", asset_class=kind, isin=ISINS[0], **{field: value}
            )


@pytest.mark.parametrize(
    "venue,currency",
    [("XNSE", "INR"), ("XBOM", "INR"), ("XNYS", "USD"), ("XNAS", "USD"), ("ARCX", "USD")],
)
def test_listing_currency_is_explicit_and_exchange_qualified(venue, currency):
    value = ListingDefinition(venue=venue, symbol="FAKE.A", quote_currency=currency)
    assert value.series == ""
    with pytest.raises(ValidationError):
        ListingDefinition(
            venue=venue, symbol="FAKE.A", quote_currency="USD" if currency == "INR" else "INR"
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"venue": "NYSE"},
        {"symbol": "fake"},
        {"symbol": ""},
        {"symbol": "A" * 33},
        {"series": "EQ\n"},
        {"quote_currency": "EUR"},
        {"owner_id": uuid4()},
    ],
)
def test_listing_rejects_ambiguous_or_overlong_fields(changes):
    with pytest.raises(ValidationError):
        ListingDefinition(
            **(dict(venue="XNSE", symbol="FAKE", series="EQ", quote_currency="INR") | changes)
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"value": 12345},
        {"value": ""},
        {"value": "x" * 65},
        {"value": "123\n"},
        {"qualifier": ""},
        {"qualifier": "dividend"},
        {"namespace": "isin"},
        {"value": "FAKE"},
    ],
)
def test_amfi_reference_requires_a_code_and_explicit_distribution_scope(changes):
    with pytest.raises(ValidationError):
        IdentifierDefinition(
            **(dict(namespace="amfi_nav", value="000123", qualifier="growth") | changes)
        )


def test_identifiers_preserve_zeros_and_case_without_guessing_a_provider_mapping():
    first = IdentifierDefinition(namespace="amfi_nav", value="000123", qualifier="idcw_payout")
    second = IdentifierDefinition(
        namespace="amfi_nav", value="000123", qualifier="idcw_reinvestment"
    )
    assert first != second and first.value == "000123"
    assert IdentifierDefinition(namespace="ubs", value="FAKE-001").value == "FAKE-001"
    with pytest.raises(ValidationError):
        IdentifierDefinition(namespace="ubs", value="FAKE-001", qualifier="growth")
    for value in (
        first,
        InstrumentDefinition(name="Synthetic Private Label", asset_class="equity", isin=ISINS[1]),
        SchemeDefinition(name="Synthetic Private Label"),
    ):
        assert "000123" not in repr(value) and "Synthetic Private Label" not in repr(value)
