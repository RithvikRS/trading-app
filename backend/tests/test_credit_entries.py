"""Exact entry roles, independent native values and private runtime revalidation."""

from dataclasses import FrozenInstanceError
from datetime import UTC, date, datetime
from decimal import Decimal
from itertools import product
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from trading_api.credit_cards import CardEntryValues
from trading_api.finance import FinancialDate, FinancialValue, FinancialValueError
from trading_db.credit_entries import (
    CreditEntryTransaction,
    CreditEntryUnavailable,
    EntryEvidence,
    new_entry_id,
    validate_entry,
)

ROLES = ("posted_debit", "posted_credit", "pending_debit", "pending_credit", "unresolved")
TREATMENTS = ("movement", "ambiguous", "unsupported")


def entry_values(**updates):
    fields = dict(
        role="posted_debit",
        treatment="movement",
        billing_amount=FinancialValue("cash", "123.40", currency="INR"),
        transaction_date=FinancialDate("2026-10-15"),
        posting_date=FinancialDate("2026-10-14"),
        original_amount=FinancialValue("cash", "1.20", currency="USD"),
    )
    fields.update(updates)
    return CardEntryValues(**fields)


@pytest.mark.parametrize("role,treatment", list(product(ROLES, TREATMENTS)))
def test_role_treatment_matrix_is_explicit(role, treatment):
    if role == "unresolved" and treatment == "movement":
        with pytest.raises(FinancialValueError):
            entry_values(role=role, treatment=treatment, posting_date=None)
    else:
        value = entry_values(role=role, treatment=treatment, posting_date=None)
        assert validate_entry(value) == value


@pytest.mark.parametrize("role", ["pending_debit", "pending_credit"])
def test_pending_role_cannot_acquire_a_posting_date_by_tampering(role):
    value = entry_values(role=role, posting_date=None)
    object.__setattr__(value, "posting_date", FinancialDate("2026-10-15"))
    with pytest.raises(CreditEntryUnavailable):
        validate_entry(value)


def test_original_absent_missing_zero_currency_and_decimal_spelling_stay_distinct():
    absent = entry_values(original_amount=None)
    missing = entry_values(
        original_amount=FinancialValue("cash", None, currency="USD", missing_reason="not_supplied")
    )
    zero = entry_values(original_amount=FinancialValue("cash", "-0.00", currency="USD"))
    native = entry_values(original_amount=FinancialValue("cash", "-0.00", currency="INR"))
    for value in (absent, missing, zero, native):
        assert validate_entry(value) == value
    assert absent != missing and missing != zero and zero != native
    assert zero.original_amount.source == "-0.00"
    assert entry_values() != entry_values(
        billing_amount=FinancialValue("cash", "123.4", currency="INR")
    )
    assert entry_values() != entry_values(
        original_amount=FinancialValue("cash", "1.2", currency="USD")
    )


@pytest.mark.parametrize(
    "transaction,posting",
    [
        (None, None),
        ("0001-01-01", "9999-12-31"),
        ("9999-12-31", "0001-01-01"),
        (None, "2026-10-15"),
        ("2026-10-15", None),
    ],
)
def test_dates_are_independent_calendar_evidence(transaction, posting):
    value = entry_values(
        transaction_date=FinancialDate(transaction) if transaction else None,
        posting_date=FinancialDate(posting) if posting else None,
    )
    assert validate_entry(value) == value


@pytest.mark.parametrize("amount_field", ["billing_amount", "original_amount"])
@pytest.mark.parametrize(
    "field,value",
    [
        ("source", "synthetic-private-marker"),
        ("value", Decimal("888.00")),
        ("value", Decimal("123.4")),
        ("value", 123.40),
        ("kind", "unit_price"),
        ("missing_reason", "not_supplied"),
        ("meaning", "tax"),
        ("base_currency", "INR"),
        ("quote_currency", "USD"),
    ],
)
def test_tampered_cash_cache_is_rejected_without_repair(amount_field, field, value, caplog, capsys):
    report = entry_values(original_amount=FinancialValue("cash", "123.40", currency="USD"))
    object.__setattr__(getattr(report, amount_field), field, value)
    with pytest.raises(CreditEntryUnavailable) as error:
        validate_entry(report)
    output = capsys.readouterr()
    assert (
        "synthetic-private-marker" not in str(error.value) + caplog.text + output.out + output.err
    )


@pytest.mark.parametrize("field,currency", [("billing_amount", "USD"), ("original_amount", "EUR")])
def test_wrong_currency_is_not_coerced_or_discarded(field, currency):
    report = entry_values()
    object.__setattr__(getattr(report, field), "currency", currency)
    with pytest.raises(CreditEntryUnavailable):
        validate_entry(report)


@pytest.mark.parametrize("field", ["billing_amount", "original_amount"])
def test_nonnegative_and_missing_cache_contracts_are_revalidated(field):
    report = entry_values()
    object.__setattr__(report, field, FinancialValue("cash", "-1", currency="INR"))
    with pytest.raises(CreditEntryUnavailable):
        validate_entry(report)
    report = entry_values(
        **{field: FinancialValue("cash", None, currency="INR", missing_reason="not_supplied")}
    )
    object.__setattr__(getattr(report, field), "value", Decimal("0"))
    with pytest.raises(CreditEntryUnavailable):
        validate_entry(report)


@pytest.mark.parametrize("name", ["transaction_date", "posting_date"])
@pytest.mark.parametrize(
    "field,value",
    [
        ("source", "2026-99-99"),
        ("value", date(2025, 1, 1)),
        ("value", True),
    ],
)
def test_tampered_dates_are_rejected(name, field, value):
    report = entry_values()
    object.__setattr__(getattr(report, name), field, value)
    with pytest.raises(CreditEntryUnavailable):
        validate_entry(report)


@pytest.mark.parametrize(
    "field",
    ["role", "treatment", "billing_amount", "original_amount", "transaction_date", "posting_date"],
)
def test_wrong_nested_types_are_private(field):
    report = entry_values()
    object.__setattr__(report, field, "synthetic-private-marker")
    with pytest.raises(CreditEntryUnavailable):
        validate_entry(report)


def test_unresolved_movement_bypass_is_rejected():
    report = entry_values(role="unresolved", treatment="unsupported")
    object.__setattr__(report, "treatment", "movement")
    with pytest.raises(CreditEntryUnavailable):
        validate_entry(report)


def test_frozen_private_evidence_and_server_allocated_identity():
    root = new_entry_id()
    assert type(root) is UUID and root.version == 4 and root != new_entry_id()
    evidence = EntryEvidence(root, 1, None, uuid4(), 1, uuid4(), datetime.now(UTC), entry_values())
    assert str(root) not in repr(evidence) and "123.40" not in repr(evidence)
    with pytest.raises(FrozenInstanceError):
        evidence.revision = 2
    assert not hasattr(evidence, "__dict__")


@pytest.mark.parametrize("value", [None, UUID(int=0), str(uuid4()), True, 1])
def test_invalid_ids_never_reach_sql(value):
    unit = CreditEntryTransaction(SimpleNamespace())
    for call in (
        lambda: unit.get(value, at_revision=1),
        lambda: unit.history(value),
        lambda: unit.list(value),
        lambda: unit.record(value, uuid4(), 1, entry_values()),
    ):
        with pytest.raises(CreditEntryUnavailable):
            call()


@pytest.mark.parametrize("value", [0, -1, 101, True, 1.0, "1", None])
def test_invalid_pages_never_reach_sql(value):
    unit = CreditEntryTransaction(SimpleNamespace())
    with pytest.raises(CreditEntryUnavailable):
        unit.history(uuid4(), limit=value)
    with pytest.raises(CreditEntryUnavailable):
        unit.list(uuid4(), limit=value)


@pytest.mark.parametrize("value", [-1, True, 1.0, "1", None, 9007199254740991])
def test_invalid_write_revisions_never_reach_sql(value):
    with pytest.raises(CreditEntryUnavailable):
        CreditEntryTransaction(SimpleNamespace()).record(
            uuid4(), uuid4(), 1, entry_values(), expected_revision=value
        )


@pytest.mark.parametrize(
    "field",
    [
        "owner_id",
        "filename",
        "card_number",
        "last_four",
        "metadata",
        "statement_id",
        "selected",
        "withdraw",
    ],
)
def test_record_accepts_no_external_or_allocation_fields(field):
    with pytest.raises(TypeError) as error:
        CreditEntryTransaction(SimpleNamespace()).record(
            uuid4(), uuid4(), 1, entry_values(), **{field: "synthetic-private-marker"}
        )
    assert "synthetic-private-marker" not in str(error.value)


@pytest.mark.parametrize(
    "change",
    [
        {"billing_amount": Decimal("999")},
        {"billing_amount": 123.40},
        {"billing_amount": Decimal("sNaN")},
        {"original_amount": True},
        {"original_currency": None},
        {"original_currency": "EUR"},
        {"original_missing": "unsupported"},
        {"role": "synthetic-private-marker"},
        {"transaction_date": "synthetic-private-marker"},
    ],
)
def test_corrupt_projection_is_rejected_privately(change, caplog, capsys):
    from trading_db.credit_entries import _evidence

    row = dict(
        id=uuid4(),
        revision=1,
        previous_revision=None,
        source_id=uuid4(),
        mapping_revision=1,
        account_id=uuid4(),
        created_at=datetime.now(UTC),
        role="posted_debit",
        treatment="movement",
        transaction_date=date(2026, 10, 15),
        posting_date=None,
        billing_source="123.40",
        billing_amount=Decimal("123.40"),
        billing_missing=None,
        original_source="1.20",
        original_amount=Decimal("1.20"),
        original_missing=None,
        original_currency="USD",
    )
    row.update(change)
    with pytest.raises(CreditEntryUnavailable) as error:
        _evidence(row)
    output = capsys.readouterr()
    assert (
        "synthetic-private-marker" not in str(error.value) + caplog.text + output.out + output.err
    )
