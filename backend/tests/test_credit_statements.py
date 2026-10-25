"""Exact/private checkpoint contracts and bounded internal operation inputs."""

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from trading_api.credit_cards import CardStatementValues
from trading_api.finance import FinancialDate, FinancialValue
from trading_db.credit_statements import (
    CreditStatementTransaction,
    CreditStatementUnavailable,
    StatementEvidence,
    new_statement_id,
    validate_statement,
)


def statement_values(**updates):
    def known(value):
        return FinancialValue("cash", value, currency="INR")

    fields = dict(
        period_start=FinancialDate("2026-09-15"),
        period_end=FinancialDate("2026-10-14"),
        statement_date=FinancialDate("2026-10-14"),
        due_date=None,
        opening_liability=known("-20.00"),
        closing_liability=known("123.40"),
        total_due=FinancialValue("cash", None, currency="INR", missing_reason="not_supplied"),
        minimum_due=known("0.00"),
    )
    fields.update(updates)
    return CardStatementValues(**fields)


def test_values_round_trip_exactly_without_inferred_dates_or_money():
    value = statement_values(
        statement_date=FinancialDate("0001-01-01"), due_date=FinancialDate("0001-01-01")
    )
    result = validate_statement(value)
    assert result == value and result is not value
    assert result.closing_liability.source == "123.40"
    assert result.total_due.value is None and result.minimum_due.source == "0.00"
    assert (
        validate_statement(
            statement_values(opening_liability=FinancialValue("cash", "-0.00", currency="INR"))
        ).opening_liability.source
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
def test_mutated_nested_money_is_rejected_privately(field, value, caplog, capsys):
    statement = statement_values()
    object.__setattr__(statement.closing_liability, field, value)
    with pytest.raises(CreditStatementUnavailable) as error:
        validate_statement(statement)
    captured = capsys.readouterr()
    assert (
        "synthetic-private-marker"
        not in str(error.value) + caplog.text + captured.out + captured.err
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("source", "2026-99-99"),
        ("value", date(2026, 9, 16)),
        ("value", True),
    ],
)
def test_mutated_nested_date_is_not_repaired(field, value):
    statement = statement_values()
    object.__setattr__(statement.period_start, field, value)
    with pytest.raises(CreditStatementUnavailable):
        validate_statement(statement)


@pytest.mark.parametrize(
    "field",
    [
        "period_start",
        "period_end",
        "statement_date",
        "due_date",
        "opening_liability",
        "closing_liability",
        "total_due",
        "minimum_due",
    ],
)
def test_wrong_nested_runtime_types_are_rejected(field):
    statement = statement_values()
    object.__setattr__(statement, field, "synthetic-private-marker")
    with pytest.raises(CreditStatementUnavailable):
        validate_statement(statement)


def test_nonnegative_minimum_and_missing_cache_cannot_be_bypassed():
    statement = statement_values()
    object.__setattr__(statement, "minimum_due", FinancialValue("cash", "-1.00", currency="INR"))
    with pytest.raises(CreditStatementUnavailable):
        validate_statement(statement)
    statement = statement_values()
    object.__setattr__(statement.total_due, "value", Decimal("0"))
    with pytest.raises(CreditStatementUnavailable):
        validate_statement(statement)


def test_private_frozen_evidence_and_server_allocated_retry_identity():
    root = new_statement_id()
    assert type(root) is UUID and root.version == 4 and root != new_statement_id()
    record = StatementEvidence(
        root, 1, None, uuid4(), 1, uuid4(), datetime.now(UTC), statement_values()
    )
    assert str(root) not in repr(record) and "123.40" not in repr(record)
    with pytest.raises(FrozenInstanceError):
        record.revision = 2
    assert not hasattr(record, "__dict__")


@pytest.mark.parametrize("value", [None, UUID(int=0), str(uuid4()), True, 1])
def test_invalid_ids_never_reach_sql(value):
    unit = CreditStatementTransaction(SimpleNamespace())
    for call in (
        lambda: unit.get(value, at_revision=1),
        lambda: unit.history(value),
        lambda: unit.list(value),
        lambda: unit.record(value, uuid4(), 1, statement_values()),
    ):
        with pytest.raises(CreditStatementUnavailable):
            call()


@pytest.mark.parametrize("value", [0, -1, 101, True, 1.0, "1", None])
def test_invalid_pages_never_reach_sql(value):
    unit = CreditStatementTransaction(SimpleNamespace())
    with pytest.raises(CreditStatementUnavailable):
        unit.history(uuid4(), limit=value)
    with pytest.raises(CreditStatementUnavailable):
        unit.list(uuid4(), limit=value)


@pytest.mark.parametrize("value", [-1, True, 1.0, "1", None, 9007199254740991])
def test_invalid_write_revisions_never_reach_sql(value):
    unit = CreditStatementTransaction(SimpleNamespace())
    with pytest.raises(CreditStatementUnavailable):
        unit.record(uuid4(), uuid4(), 1, statement_values(), expected_revision=value)


@pytest.mark.parametrize(
    "field", ["owner_id", "filename", "card_number", "last_four", "metadata", "reference"]
)
def test_record_has_no_external_or_caller_owned_payload(field, capsys):
    unit = CreditStatementTransaction(SimpleNamespace())
    with pytest.raises(TypeError) as error:
        unit.record(uuid4(), uuid4(), 1, statement_values(), **{field: "synthetic-private-marker"})
    assert "synthetic-private-marker" not in str(error.value) + capsys.readouterr().err


def test_decimal_spelling_is_part_of_evidence_equality():
    first = statement_values()
    second = replace(first, closing_liability=FinancialValue("cash", "123.4", currency="INR"))
    assert first.closing_liability.value == second.closing_liability.value
    assert first != second


@pytest.mark.parametrize(
    "change",
    [
        {"closing_liability_amount": Decimal("999.00")},
        {"period_start": None},
        {"closing_liability_source": "synthetic-private-marker"},
    ],
)
def test_corrupt_retained_projection_fails_with_private_error(change, capsys, caplog):
    from trading_db.credit_statements import _evidence

    values = statement_values()
    row = dict(
        id=uuid4(),
        revision=1,
        previous_revision=None,
        source_id=uuid4(),
        mapping_revision=1,
        account_id=uuid4(),
        created_at=datetime.now(UTC),
    )
    for name in ("period_start", "period_end", "statement_date", "due_date"):
        value = getattr(values, name)
        row[name] = value.value if value is not None else None
    for name in ("opening_liability", "closing_liability", "total_due", "minimum_due"):
        value = getattr(values, name)
        row.update(
            {
                name + "_source": value.source,
                name + "_amount": value.value,
                name + "_missing": value.missing_reason,
            }
        )
    row.update(change)
    with pytest.raises(CreditStatementUnavailable) as error:
        _evidence(row)
    captured = capsys.readouterr()
    assert (
        "synthetic-private-marker"
        not in str(error.value) + caplog.text + captured.out + captured.err
    )
