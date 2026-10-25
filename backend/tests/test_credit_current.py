"""Current reports retain native values and source-local instants privately."""

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from trading_api.credit_cards import CardCurrentValues
from trading_api.finance import FinancialDate, FinancialInstant, FinancialValue
from trading_db.credit_current import (
    CreditCurrentTransaction,
    CreditCurrentUnavailable,
    CurrentEvidence,
    new_current_id,
    validate_current,
)


def current_values(**updates):
    def known(value):
        return FinancialValue("cash", value, currency="INR")

    fields = dict(
        as_of_date=FinancialDate("2026-10-15"),
        as_of_instant=FinancialInstant("2026-10-15T00:01:02.1200+05:30"),
        outstanding=known("123.40"),
        unbilled=FinancialValue("cash", None, currency="INR", missing_reason="not_supplied"),
        credit_limit=known("0.00"),
        available_credit=known("-20.00"),
    )
    fields.update(updates)
    return CardCurrentValues(**fields)


def test_exact_local_day_precision_missing_and_independent_signed_values():
    value = current_values()
    result = validate_current(value)
    assert result == value and result is not value
    assert result.as_of_date.source == "2026-10-15"
    assert result.as_of_instant.value.date() == date(2026, 10, 14)
    assert result.as_of_instant.source == "2026-10-15T00:01:02.1200+05:30"
    assert result.outstanding.source == "123.40"
    assert result.unbilled.value is None and result.credit_limit.source == "0.00"
    for day in ("0001-01-01", "9999-12-31"):
        assert validate_current(current_values(as_of_date=FinancialDate(day), as_of_instant=None))
    assert (
        validate_current(
            current_values(outstanding=FinancialValue("cash", "-0.00", currency="INR"))
        ).outstanding.source
        == "-0.00"
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("source", "synthetic-private-marker"),
        ("value", Decimal("888.00")),
        ("value", Decimal("123.4")),
        ("value", 123.40),
        ("currency", "USD"),
        ("kind", "unit_price"),
        ("missing_reason", "not_supplied"),
        ("meaning", "tax"),
        ("base_currency", "INR"),
        ("quote_currency", "USD"),
    ],
)
def test_tampered_cash_is_not_repaired(field, value, caplog, capsys):
    report = current_values()
    object.__setattr__(report.outstanding, field, value)
    with pytest.raises(CreditCurrentUnavailable) as error:
        validate_current(report)
    output = capsys.readouterr()
    assert (
        "synthetic-private-marker" not in str(error.value) + caplog.text + output.out + output.err
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("source", "synthetic-private-marker"),
        ("source_offset", "+00:00"),
        ("fractional_digits", True),
        ("fractional_digits", 2),
        ("value", datetime(2026, 10, 14, 18, 31, 2, 120000)),
        ("value", datetime(2026, 10, 14, 18, 31, 2, 120000, tzinfo=UTC, fold=1)),
        (
            "value",
            datetime(
                2026, 10, 15, 0, 1, 2, 120000, tzinfo=timezone(timedelta(hours=5, minutes=30))
            ),
        ),
    ],
)
def test_tampered_instant_cache_cannot_pass_equal_instant_comparison(field, value):
    report = current_values()
    object.__setattr__(report.as_of_instant, field, value)
    with pytest.raises(CreditCurrentUnavailable):
        validate_current(report)


@pytest.mark.parametrize(
    "field,value", [("source", "2026-99-99"), ("value", date(2026, 10, 16)), ("value", True)]
)
def test_tampered_date_is_rejected(field, value):
    report = current_values()
    object.__setattr__(report.as_of_date, field, value)
    with pytest.raises(CreditCurrentUnavailable):
        validate_current(report)


@pytest.mark.parametrize(
    "field",
    ["as_of_date", "as_of_instant", "outstanding", "unbilled", "credit_limit", "available_credit"],
)
def test_counterfeit_nested_objects_are_private(field):
    report = current_values()
    object.__setattr__(report, field, "synthetic-private-marker")
    with pytest.raises(CreditCurrentUnavailable):
        validate_current(report)


def test_credit_limit_missing_cache_and_instant_day_contracts_revalidate():
    report = current_values()
    object.__setattr__(report, "credit_limit", FinancialValue("cash", "-1", currency="INR"))
    with pytest.raises(CreditCurrentUnavailable):
        validate_current(report)
    report = current_values()
    object.__setattr__(report.unbilled, "value", Decimal("0"))
    with pytest.raises(CreditCurrentUnavailable):
        validate_current(report)
    report = current_values()
    object.__setattr__(report, "as_of_date", FinancialDate("2026-10-14"))
    with pytest.raises(CreditCurrentUnavailable):
        validate_current(report)


def test_exact_spelling_remains_part_of_retry_equality():
    first = current_values(as_of_instant=FinancialInstant("2026-10-15T00:00:00Z"))
    same_instant = replace(first, as_of_instant=FinancialInstant("2026-10-15T00:00:00+00:00"))
    same_money = replace(first, outstanding=FinancialValue("cash", "123.4", currency="INR"))
    assert first.as_of_instant.value == same_instant.as_of_instant.value
    assert first.outstanding.value == same_money.outstanding.value
    assert first != same_instant and first != same_money


def test_private_frozen_evidence_and_server_retry_id():
    root = new_current_id()
    assert type(root) is UUID and root.version == 4 and root != new_current_id()
    record = CurrentEvidence(
        root, 1, None, uuid4(), 1, uuid4(), datetime.now(UTC), current_values()
    )
    assert str(root) not in repr(record) and "123.40" not in repr(record)
    with pytest.raises(FrozenInstanceError):
        record.revision = 2
    assert not hasattr(record, "__dict__")


@pytest.mark.parametrize("value", [None, UUID(int=0), str(uuid4()), True, 1])
def test_invalid_ids_never_reach_sql(value):
    unit = CreditCurrentTransaction(SimpleNamespace())
    for call in (
        lambda: unit.get(value, at_revision=1),
        lambda: unit.history(value),
        lambda: unit.list(value),
        lambda: unit.record(value, uuid4(), 1, current_values()),
    ):
        with pytest.raises(CreditCurrentUnavailable):
            call()


@pytest.mark.parametrize("value", [0, -1, 101, True, 1.0, "1", None])
def test_invalid_pages_never_reach_sql(value):
    unit = CreditCurrentTransaction(SimpleNamespace())
    with pytest.raises(CreditCurrentUnavailable):
        unit.history(uuid4(), limit=value)
    with pytest.raises(CreditCurrentUnavailable):
        unit.list(uuid4(), limit=value)


@pytest.mark.parametrize("value", [-1, True, 1.0, "1", None, 9007199254740991])
def test_invalid_revisions_never_reach_sql(value):
    unit = CreditCurrentTransaction(SimpleNamespace())
    with pytest.raises(CreditCurrentUnavailable):
        unit.record(uuid4(), uuid4(), 1, current_values(), expected_revision=value)


@pytest.mark.parametrize("field", ["owner_id", "filename", "card_number", "last_four", "metadata"])
def test_external_fields_not_accepted(field):
    unit = CreditCurrentTransaction(SimpleNamespace())
    with pytest.raises(TypeError) as error:
        unit.record(uuid4(), uuid4(), 1, current_values(), **{field: "synthetic-private-marker"})
    assert "synthetic-private-marker" not in str(error.value)


@pytest.mark.parametrize(
    "change",
    [
        {"outstanding_amount": Decimal("999")},
        {"as_of_date": None},
        {"as_of_instant": "synthetic-private-marker"},
        {"as_of_instant": "2026-10-14T00:00:00Z"},
        {"outstanding_source": "synthetic-private-marker"},
    ],
)
def test_corrupt_projection_is_private(change, caplog, capsys):
    from trading_db.credit_current import ROLES, _evidence

    values = current_values()
    row = dict(
        id=uuid4(),
        revision=1,
        previous_revision=None,
        source_id=uuid4(),
        mapping_revision=1,
        account_id=uuid4(),
        created_at=datetime.now(UTC),
        as_of_date=values.as_of_date.value,
        as_of_instant=values.as_of_instant.source,
    )
    for role in ROLES:
        value = getattr(values, role)
        row.update(
            {
                role + "_source": value.source,
                role + "_amount": value.value,
                role + "_missing": value.missing_reason,
            }
        )
    row.update(change)
    with pytest.raises(CreditCurrentUnavailable) as error:
        _evidence(row)
    output = capsys.readouterr()
    assert (
        "synthetic-private-marker" not in str(error.value) + caplog.text + output.out + output.err
    )
