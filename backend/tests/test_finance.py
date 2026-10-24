"""Independent financial examples and hostile input/context regression cases."""

import json
from dataclasses import FrozenInstanceError
from datetime import UTC, date, datetime
from decimal import ROUND_DOWN, Decimal, Inexact, Rounded, localcontext
from fractions import Fraction

import pytest

from trading_api.finance import (
    MAX_SUM_ITEMS,
    FinancialDate,
    FinancialInstant,
    FinancialValue,
    FinancialValueError,
    display_valuation,
    sum_cash,
)


def cash(value, currency="INR", **kwargs):
    return FinancialValue("cash", value, currency=currency, **kwargs)


def price(value, currency="INR"):
    return FinancialValue("unit_price", value, currency=currency)


def quantity(value, kind="position_quantity"):
    return FinancialValue(kind, value)


def rate(value, base="INR", quote="USD"):
    return FinancialValue("fx_rate", value, base_currency=base, quote_currency=quote)


@pytest.mark.parametrize(
    "kind,source,context",
    [
        ("cash", "-999999999999999999.99", {"currency": "INR"}),
        ("cash", "0.01", {"currency": "USD"}),
        (
            "monetary_evidence",
            "999999999999999999.12345678",
            {"currency": "USD", "meaning": "reported_tax_basis"},
        ),
        ("quantity_movement", "-999999999999999999.999999999999", {}),
        ("position_quantity", "0.000000000001", {}),
        ("lot_quantity", "999999999999999999.999999999999", {}),
        ("unit_price", "999999999999999999.999999999999", {"currency": "INR"}),
        ("fx_rate", "0.000000000001", {"base_currency": "USD", "quote_currency": "INR"}),
        ("display_amount", "-123.45", {"currency": "INR"}),
    ],
)
def test_exact_values_and_json_round_trip(kind, source, context):
    original = FinancialValue(kind, source, **context)
    encoded = json.dumps(original.to_dict(), allow_nan=False)
    payload = json.loads(encoded)
    assert isinstance(payload["value"], str)
    assert payload["value"] == source
    reconstructed = FinancialValue(payload.pop("kind"), payload.pop("value"), **payload)
    assert reconstructed == original
    assert original.source == source
    assert original.value.as_tuple() == Decimal(source).as_tuple()


@pytest.mark.parametrize(
    "source",
    [
        0,
        1,
        1.1,
        True,
        False,
        Decimal("1.1"),
        b"1.1",
        [],
        {},
        "",
        " 1",
        "1 ",
        "1\n",
        "+1",
        "01",
        "-01",
        "00.10",
        ".1",
        "1.",
        "1,000",
        "1_000",
        "1e2",
        "1E-2",
        "NaN",
        "sNaN",
        "Infinity",
        "-Infinity",
        "١٢.٣",
        "１２.３",
        "−1",
        "1\x00",
        "1/2",
        pytest.param("9" * 100_000, id="oversized-number"),
    ],
)
def test_decimal_boundary_rejects_coercion_nonfinite_and_noncanonical_syntax(source):
    with pytest.raises(FinancialValueError):
        cash(source)


@pytest.mark.parametrize("currency", [None, "EUR", "inr", " INR", 1, True, [], {}])
def test_only_exact_supported_currency_codes_are_accepted(currency):
    with pytest.raises(FinancialValueError):
        cash("1", currency)


@pytest.mark.parametrize(
    "kind,context,scale",
    [
        ("cash", {"currency": "INR"}, 2),
        ("monetary_evidence", {"currency": "USD", "meaning": "fee"}, 8),
        ("quantity_movement", {}, 12),
        ("position_quantity", {}, 12),
        ("lot_quantity", {}, 12),
        ("unit_price", {"currency": "USD"}, 12),
        ("fx_rate", {"base_currency": "INR", "quote_currency": "USD"}, 12),
        ("display_amount", {"currency": "USD"}, 2),
    ],
)
def test_scale_and_magnitude_are_rejected_without_rounding(kind, context, scale):
    accepted = "999999999999999999." + "9" * scale
    assert FinancialValue(kind, accepted, **context).to_dict()["value"] == accepted
    for unsupported in ["1." + "0" * (scale + 1), "1000000000000000000", "-1000000000000000000"]:
        with pytest.raises(FinancialValueError):
            FinancialValue(kind, unsupported, **context)


@pytest.mark.parametrize("source", ["-0", "-0.0", "-0.00"])
def test_negative_zero_normalizes_without_losing_source_scale_or_text(source):
    value = cash(source)
    assert value.source == source
    assert not value.value.is_signed()
    assert value.to_dict()["value"] == source[1:]


@pytest.mark.parametrize("kind", ["position_quantity", "lot_quantity"])
def test_long_quantities_allow_zero_but_reject_negative(kind):
    assert quantity("-0.000", kind).value == 0
    with pytest.raises(FinancialValueError):
        quantity("-0.000000000001", kind)


@pytest.mark.parametrize("factory", [price, rate])
@pytest.mark.parametrize("source", ["0", "-0.000", "-1"])
def test_usable_prices_and_rates_are_strictly_positive(factory, source):
    with pytest.raises(FinancialValueError):
        factory(source)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"kind": "other"},
        {"kind": []},
        {"kind": True},
        {"kind": "position_quantity", "currency": "INR"},
        {"kind": "cash", "base_currency": "INR"},
        {"kind": "cash", "quote_currency": "USD"},
        {"kind": "cash", "meaning": "fee"},
        {"kind": "monetary_evidence"},
        {"kind": "monetary_evidence", "currency": "INR", "meaning": "unknown"},
        {"kind": "monetary_evidence", "currency": "INR", "meaning": []},
        {"kind": "fx_rate"},
        {"kind": "fx_rate", "base_currency": "INR", "quote_currency": "INR"},
        {"kind": "fx_rate", "base_currency": "INR", "quote_currency": "USD", "currency": "INR"},
    ],
)
def test_kind_and_context_combinations_are_closed(kwargs):
    with pytest.raises(FinancialValueError):
        FinancialValue(source="1", **kwargs)


@pytest.mark.parametrize(
    "meaning", ["acquisition_cost", "reported_tax_basis", "discount_amount", "fee", "withholding"]
)
def test_monetary_evidence_preserves_its_meaning_separately_from_cash(meaning):
    evidence = FinancialValue("monetary_evidence", "12.12345678", currency="USD", meaning=meaning)
    assert evidence.to_dict()["meaning"] == meaning
    with pytest.raises(FinancialValueError):
        sum_cash([evidence], currency="USD")


@pytest.mark.parametrize(
    "reason", ["not_supplied", "incomplete_history", "unsupported", "conflicting_evidence"]
)
def test_unknown_is_explicit_and_never_zero(reason):
    absent = cash(None, missing_reason=reason)
    payload = json.loads(json.dumps(absent.to_dict()))
    assert payload["value"] is None
    assert payload["missing_reason"] == reason
    assert cash("0").to_dict()["value"] == "0"
    assert cash("0").to_dict()["missing_reason"] is None
    with pytest.raises(FinancialValueError):
        cash("0", missing_reason=reason)
    with pytest.raises(FinancialValueError):
        sum_cash([absent], currency="INR")


@pytest.mark.parametrize("reason", [None, "", "invented", 1, False, [], {}])
def test_missing_values_require_an_allowlisted_reason(reason):
    with pytest.raises(FinancialValueError):
        cash(None, missing_reason=reason)


def test_unknown_values_still_require_valid_currency_and_kind_context():
    with pytest.raises(FinancialValueError):
        FinancialValue("unit_price", None, missing_reason="not_supplied")
    with pytest.raises(FinancialValueError):
        FinancialValue("monetary_evidence", None, currency="INR", missing_reason="not_supplied")
    assert (
        FinancialValue(
            "fx_rate",
            None,
            base_currency="INR",
            quote_currency="USD",
            missing_reason="not_supplied",
        ).value
        is None
    )


def test_exact_cash_sum_preserves_cancellation_cents_and_currency():
    amounts = [cash("999999999999999999.99"), cash("0.01"), cash("-999999999999999999.99")]
    assert sum_cash(amounts, currency="INR").to_dict()["value"] == "0.01"
    assert sum_cash([cash("0.10"), cash("0.20"), cash("-0.30")], currency="INR").value == 0
    assert sum_cash([cash("1.23", "USD")], currency="USD").currency == "USD"


@pytest.mark.parametrize(
    "values",
    [
        [],
        [cash("1"), cash("2", "USD")],
        [quantity("1")],
        [None],
        [1.2],
        [cash("999999999999999999.99"), cash("0.01")],
    ],
)
def test_cash_sum_rejects_empty_mixed_unknown_wrong_kind_and_output_overflow(values):
    with pytest.raises(FinancialValueError):
        sum_cash(values, currency="INR")


def test_cash_sum_bounds_consumption_of_an_unending_input():
    consumed = 0

    def unending():
        nonlocal consumed
        while True:
            consumed += 1
            yield cash("0.01")

    assert sum_cash([cash("0.01")] * MAX_SUM_ITEMS, currency="INR").value == Decimal("100.00")
    with pytest.raises(FinancialValueError):
        sum_cash(unending(), currency="INR")
    assert consumed == MAX_SUM_ITEMS + 1


@pytest.mark.parametrize(
    "units,quote,expected",
    [
        ("1", "2.344", "2.34"),
        ("1", "2.345", "2.35"),
        ("-1", "2.345", "-2.35"),
        ("1", "0.004", "0.00"),
        ("-1", "0.004", "0.00"),
        ("0", "200", "0.00"),
    ],
)
def test_final_display_rounding_is_half_away_from_zero(units, quote, expected):
    result = display_valuation(quantity(units, "quantity_movement"), price(quote))
    assert result.to_dict()["value"] == expected
    assert result.kind == "display_amount"
    with pytest.raises(FinancialValueError):
        sum_cash([result], currency="INR")


def test_fx_is_directional_and_only_the_final_result_is_rounded():
    result = display_valuation(quantity("1"), price("1.005", "USD"), fx=rate("2", "USD", "INR"))
    assert result.to_dict()["value"] == "2.01"  # Rounding before FX would incorrectly give 2.02.
    assert result.currency == "INR"
    with pytest.raises(FinancialValueError):
        display_valuation(quantity("1"), price("1", "USD"), fx=rate("2"))


@pytest.mark.parametrize(
    "units,quote,fx",
    [
        ("123456789.123456789012", "0.000000123456", "83.123456789012"),
        ("999999999999999999.999999999999", "0.000000000001", "1.123456789012"),
        ("-12345.999999999999", "98.999999999999", "83.999999999999"),
        ("0.000000000001", "0.000000000001", "0.000000000001"),
    ],
)
def test_high_precision_valuation_matches_an_independent_rational_oracle(units, quote, fx):
    exact_cents = Fraction(units) * Fraction(quote) * Fraction(fx) * 100
    magnitude = abs(exact_cents)
    whole, remainder = divmod(magnitude.numerator, magnitude.denominator)
    cents = whole + int(2 * remainder >= magnitude.denominator)
    sign = "-" if exact_cents < 0 and cents else ""
    expected = f"{sign}{cents // 100}.{cents % 100:02d}"
    actual = display_valuation(
        quantity(units, "quantity_movement"), price(quote, "USD"), fx=rate(fx, "USD", "INR")
    )
    assert actual.to_dict()["value"] == expected


@pytest.mark.parametrize(
    "units,quote,fx",
    [
        (cash("1"), price("1"), None),
        (quantity("1"), cash("1"), None),
        (quantity("1"), price("1"), cash("1")),
        (
            FinancialValue("position_quantity", None, missing_reason="incomplete_history"),
            price("1"),
            None,
        ),
        (
            quantity("1"),
            FinancialValue("unit_price", None, currency="INR", missing_reason="not_supplied"),
            None,
        ),
        (
            quantity("1"),
            price("1"),
            FinancialValue(
                "fx_rate",
                None,
                base_currency="INR",
                quote_currency="USD",
                missing_reason="not_supplied",
            ),
        ),
        (quantity("1"), price("999999999999999999.995"), None),
        (quantity("999999999999999999"), price("999999999999999999"), None),
    ],
)
def test_display_calculations_reject_wrong_kinds_missing_operands_and_overflow(units, quote, fx):
    with pytest.raises(FinancialValueError):
        display_valuation(units, quote, fx=fx)


def test_hostile_ambient_decimal_context_cannot_round_values_or_change_results():
    with localcontext() as ambient:
        ambient.prec = 2
        ambient.rounding = ROUND_DOWN
        ambient.Emin, ambient.Emax = -2, 2
        for signal in ambient.traps:
            ambient.traps[signal] = True
        ambient.flags[Inexact] = True
        ambient.flags[Rounded] = True
        before = (dict(ambient.flags), dict(ambient.traps), ambient.prec, ambient.rounding)
        assert cash("999999999999999999.99").to_dict()["value"] == "999999999999999999.99"
        assert (
            sum_cash([cash("123.45"), cash("-23.44")], currency="INR").to_dict()["value"]
            == "100.01"
        )
        assert display_valuation(quantity("1"), price("1234.565")).to_dict()["value"] == "1234.57"
        assert (dict(ambient.flags), dict(ambient.traps), ambient.prec, ambient.rounding) == before


@pytest.mark.parametrize("source", ["2024-02-29", "0001-01-01", "9999-12-31", "2026-10-24"])
def test_calendar_dates_round_trip_without_becoming_instants(source):
    value = FinancialDate(source)
    assert type(value.value) is date
    assert value.to_dict() == {"value": source, "precision": "date"}
    assert value.source == source


@pytest.mark.parametrize(
    "source",
    [
        "2026-02-29",
        "2026-13-01",
        "0000-01-01",
        "2026-04-31",
        "20261024",
        "24/10/2026",
        "2026-W43-6",
        "2026-1-1",
        "2026-10-24\n",
        "2026-10-24T00:00:00Z",
        "２０２６-10-24",
        None,
        20261024,
        True,
        date(2026, 10, 24),
        datetime(2026, 10, 24),
        pytest.param("x" * 100_000, id="oversized-date"),
    ],
)
def test_calendar_dates_reject_invalid_dates_alternate_forms_and_coercion(source):
    with pytest.raises(FinancialValueError):
        FinancialDate(source)


@pytest.mark.parametrize(
    "source,utc,offset,precision",
    [
        ("2026-10-24T01:02:03Z", "2026-10-24T01:02:03Z", "Z", 0),
        ("2026-10-24T01:02:03.120+05:30", "2026-10-23T19:32:03.120Z", "+05:30", 3),
        ("2026-12-31T23:59:59.123456-02:00", "2027-01-01T01:59:59.123456Z", "-02:00", 6),
        ("2026-01-01T00:00:00.0+14:00", "2025-12-31T10:00:00.0Z", "+14:00", 1),
        ("2026-01-01T00:00:00-14:00", "2026-01-01T14:00:00Z", "-14:00", 0),
        ("0001-01-01T00:00:00+00:00", "0001-01-01T00:00:00Z", "+00:00", 0),
    ],
)
def test_instants_normalize_utc_without_losing_offset_or_fractional_precision(
    source, utc, offset, precision
):
    instant = FinancialInstant(source)
    assert instant.value.tzinfo is UTC
    assert instant.source == source
    assert instant.to_dict() == {
        "value": utc,
        "precision": "instant",
        "source_offset": offset,
        "fractional_digits": precision,
    }
    assert FinancialInstant(utc).value == instant.value


@pytest.mark.parametrize(
    "source",
    [
        "2026-10-24",
        "2026-10-24T12:00:00",
        "2026-10-24 12:00:00Z",
        "2026-10-24T12:00Z",
        "2026-10-24T12:00:00z",
        "2026-10-24T12:00:00+0530",
        "2026-10-24T12:00:00-00:00",
        "2026-10-24T12:00:00+00:60",
        "2026-10-24T12:00:00+14:01",
        "2026-10-24T12:00:00-15:00",
        "2026-10-24T12:00:00+24:00",
        "2026-10-24T12:00:00.1234567Z",
        "2026-10-24T24:00:00Z",
        "2026-10-24T12:00:60Z",
        "2026-02-29T12:00:00Z",
        "20261024T12:00:00Z",
        "2026-10-24T12:00:00Z\n",
        "0001-01-01T00:00:00+00:01",
        "9999-12-31T23:59:59-00:01",
        None,
        1792843200,
        True,
        datetime(2026, 10, 24, tzinfo=UTC),
        pytest.param("x" * 100_000, id="oversized-instant"),
    ],
)
def test_instants_reject_ambiguous_excess_precision_and_out_of_range_inputs(source):
    with pytest.raises(FinancialValueError):
        FinancialInstant(source)


def test_repeated_local_hour_requires_and_retains_an_explicit_offset():
    earlier = FinancialInstant("2026-11-01T01:30:00-04:00")
    later = FinancialInstant("2026-11-01T01:30:00-05:00")
    assert (later.value - earlier.value).total_seconds() == 3600
    assert earlier.source_offset != later.source_offset
    with pytest.raises(FinancialValueError):
        FinancialInstant("2026-11-01T01:30:00")


@pytest.mark.parametrize(
    "instance",
    [cash("123456.78"), FinancialDate("2026-10-24"), FinancialInstant("2026-10-24T12:34:56Z")],
)
def test_values_are_immutable_and_default_reprs_omit_source_and_value(instance):
    assert instance.source not in repr(instance)
    assert str(instance.value) not in repr(instance)
    with pytest.raises(FrozenInstanceError):
        instance.source = "changed"
    with pytest.raises(FrozenInstanceError):
        instance.value = None


@pytest.mark.parametrize("factory", [cash, FinancialDate, FinancialInstant])
def test_validation_messages_do_not_echo_sensitive_source(factory):
    private = "synthetic-private-statement-text"
    with pytest.raises(FinancialValueError) as error:
        factory(private)
    assert private not in str(error.value)
    assert private not in repr(error.value)
