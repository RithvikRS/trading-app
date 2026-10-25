"""Synthetic liability evidence and exact, deliberately incomplete reconciliation."""

from dataclasses import FrozenInstanceError, fields, replace
from datetime import date
from decimal import ROUND_DOWN, Decimal, Inexact, Rounded, localcontext

import pytest

from trading_api.credit_cards import (
    MAX_CARD_ENTRIES,
    CardCurrentValues,
    CardEntryValues,
    CardReconciliation,
    CardStatementValues,
    reconcile_card_statement,
)
from trading_api.finance import (
    FinancialDate,
    FinancialInstant,
    FinancialValue,
    FinancialValueError,
)


def cash(source, currency="INR"):
    return FinancialValue(
        "cash", source, currency=currency, missing_reason="not_supplied" if source is None else None
    )


def day(source):
    return FinancialDate(source)


def statement(**changes):
    return CardStatementValues(
        **(
            dict(
                period_start=day("2026-09-16"),
                period_end=day("2026-10-15"),
                statement_date=day("2026-10-15"),
                due_date=day("2026-11-04"),
                opening_liability=cash("10000.00"),
                closing_liability=cash("15000.00"),
                total_due=cash("15000.00"),
                minimum_due=cash("750.00"),
            )
            | changes
        )
    )


def current(**changes):
    return CardCurrentValues(
        **(
            dict(
                as_of_date=day("2026-10-20"),
                as_of_instant=None,
                outstanding=cash("12400.00"),
                unbilled=cash(None),
                credit_limit=cash("100000"),
                available_credit=cash(None),
            )
            | changes
        )
    )


def entry(amount="5000.00", role="posted_debit", **changes):
    return CardEntryValues(
        **(
            dict(
                role=role,
                treatment="movement",
                billing_amount=cash(amount),
                transaction_date=day("2026-10-01"),
                posting_date=day("2026-10-02"),
                original_amount=None,
            )
            | changes
        )
    )


def test_complete_posted_debits_credits_reconcile_without_due_or_current_values():
    supplied = statement(total_due=cash("900"), minimum_due=cash("1000"))
    rows = (entry("8500"), entry("3500"), entry("1000"), entry("8000", "posted_credit"))
    result = reconcile_card_statement(supplied, rows, coverage="complete")
    assert result.state == "matched" and result.reason is None
    assert result.calculated_closing.value == Decimal("15000.00")
    assert result.difference.value == Decimal("0.00")
    assert supplied.total_due.source == "900" and supplied.minimum_due.source == "1000"
    assert current().outstanding.value == Decimal("12400.00")


def test_mismatch_retains_exact_difference_without_adjusting_source_or_inventing_an_entry():
    supplied = statement()
    result = reconcile_card_statement(supplied, (entry("4999.99"),), coverage="complete")
    assert result.state == "mismatched"
    assert result.calculated_closing.source == "14999.99"
    assert result.difference.source == "0.01"
    assert supplied.closing_liability.source == "15000.00"


def test_overpayment_and_credit_balances_preserve_negative_values_without_paid_status():
    supplied = statement(
        opening_liability=cash("100"),
        closing_liability=cash("-20"),
        total_due=cash("-20"),
        minimum_due=cash("0"),
        due_date=None,
    )
    result = reconcile_card_statement(
        supplied, (entry("120", "posted_credit"),), coverage="complete"
    )
    assert result.state == "matched" and result.calculated_closing.value == Decimal("-20")
    assert supplied.total_due.value == Decimal("-20") and supplied.due_date is None
    observed = current(
        outstanding=cash("-20"),
        unbilled=cash("-5"),
        credit_limit=cash("1000"),
        available_credit=cash("1020"),
    )
    assert observed.available_credit.value > observed.credit_limit.value
    assert current(available_credit=cash("-12")).available_credit.value == Decimal("-12")
    assert not hasattr(result, "paid") and not hasattr(result, "overdue")


def test_missing_checkpoints_and_due_fields_are_not_zero_or_required_for_arithmetic():
    supplied = statement(total_due=cash(None), minimum_due=cash(None), due_date=None)
    assert reconcile_card_statement(supplied, (entry(),), coverage="complete").state == "matched"
    assert supplied.total_due.value is None and supplied.total_due.missing_reason == "not_supplied"
    for name in ("opening_liability", "closing_liability"):
        result = reconcile_card_statement(
            replace(supplied, **{name: cash(None)}), (entry(),), coverage="complete"
        )
        assert result.state == "unavailable" and result.reason == "missing_checkpoint"
        assert result.calculated_closing is None and result.difference is None
    zero = cash("0.00")
    assert zero.value == 0 and zero.missing_reason is None
    assert current().unbilled.value is None and current().available_credit.value is None


@pytest.mark.parametrize(
    "coverage,reason", [("partial", "incomplete_coverage"), ("unknown", "unknown_coverage")]
)
def test_balancing_rows_and_empty_rows_do_not_upgrade_coverage(coverage, reason):
    for rows in ((entry(),), ()):
        result = reconcile_card_statement(statement(), rows, coverage=coverage)
        assert result.state == "unavailable" and result.reason == reason
        assert result.calculated_closing is None and result.difference is None


def test_explicit_complete_empty_scope_and_repeated_equal_entries_have_distinct_meanings():
    supplied = statement(opening_liability=cash("0"), closing_liability=cash("0"))
    assert reconcile_card_statement(supplied, (), coverage="complete").state == "matched"
    assert reconcile_card_statement(statement(), (), coverage="complete").state == "mismatched"
    same = entry("2500")
    assert (
        reconcile_card_statement(statement(), (same, same), coverage="complete").state == "matched"
    )
    assert reconcile_card_statement(statement(), (same,), coverage="complete").state == "mismatched"


@pytest.mark.parametrize("role", ["pending_debit", "pending_credit"])
def test_pending_entries_do_not_contribute_even_with_unknown_amounts_and_dates(role):
    pending = entry(None, role, posting_date=None, transaction_date=None, treatment="unsupported")
    assert (
        reconcile_card_statement(statement(), (entry(), pending), coverage="complete").state
        == "matched"
    )


@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"treatment": "ambiguous"}, "ambiguous_entry"),
        ({"treatment": "unsupported"}, "unsupported_entry"),
        ({"role": "unresolved", "treatment": "ambiguous"}, "unresolved_entry"),
        ({"posting_date": None}, "missing_posting_date"),
        ({"billing_amount": cash(None)}, "missing_billing_amount"),
        ({"posting_date": day("2026-09-15")}, "outside_period"),
        ({"posting_date": day("2026-10-16")}, "outside_period"),
    ],
)
def test_uncertain_or_wrong_scope_posted_entries_withhold_totals(changes, reason):
    result = reconcile_card_statement(statement(), (entry(**changes),), coverage="complete")
    assert result.state == "unavailable" and result.reason == reason
    assert result.calculated_closing is None and result.difference is None


def test_independent_dates_and_source_local_instant_are_preserved_without_synthetic_ordering():
    supplied = statement(statement_date=day("2026-09-01"), due_date=day("2026-08-01"))
    independent = entry(transaction_date=day("2026-10-30"), posting_date=day("2026-09-16"))
    assert (
        reconcile_card_statement(supplied, (independent,), coverage="complete").state == "matched"
    )
    assert (
        reconcile_card_statement(
            supplied, (replace(independent, posting_date=day("2026-10-15")),), coverage="complete"
        ).state
        == "matched"
    )
    precise = current(as_of_instant=FinancialInstant("2026-10-20T00:30:00.120+05:30"))
    assert precise.as_of_instant.value.date() == date(2026, 10, 19)
    assert precise.as_of_date.source == "2026-10-20"
    assert precise.as_of_instant.source.endswith(".120+05:30")


def test_original_currency_values_are_separate_and_never_used_as_a_conversion():
    original = cash("12.30", "USD")
    supplied = entry(original_amount=original)
    assert supplied.original_amount.source == "12.30"
    assert (
        reconcile_card_statement(statement(), (supplied,), coverage="complete").state == "matched"
    )
    independent = replace(supplied, original_amount=cash("9999", "INR"))
    assert independent.billing_amount.value == Decimal("5000")
    assert (
        reconcile_card_statement(statement(), (independent,), coverage="complete").state
        == "matched"
    )
    assert entry(original_amount=cash(None, "USD")).original_amount.value is None


def test_decimal_context_cannot_round_native_arithmetic_or_change_global_flags():
    supplied = statement(opening_liability=cash("0.01"), closing_liability=cash("12345.68"))
    movement = entry("12345.67")
    with localcontext() as context:
        context.prec = 2
        context.rounding = ROUND_DOWN
        context.traps[Inexact] = True
        context.traps[Rounded] = True
        context.clear_flags()
        result = reconcile_card_statement(supplied, (movement,), coverage="complete")
        assert result.state == "matched"
        assert result.calculated_closing.source == "12345.68"
        assert not any(context.flags.values())


@pytest.mark.parametrize(
    "opening,closing,amount,role",
    [
        ("999999999999999999.99", "0", "0.01", "posted_debit"),
        ("-999999999999999999.99", "0", "0.01", "posted_credit"),
        ("999999999999999999.99", "-999999999999999999.99", "0", "posted_debit"),
    ],
)
def test_calculated_amount_or_difference_outside_bounds_is_unavailable(
    opening, closing, amount, role
):
    supplied = statement(opening_liability=cash(opening), closing_liability=cash(closing))
    result = reconcile_card_statement(supplied, (entry(amount, role),), coverage="complete")
    assert result.state == "unavailable" and result.reason == "arithmetic_bounds"
    assert result.calculated_closing is None and result.difference is None


def test_row_budget_accepts_limit_and_rejects_oversize_or_arbitrary_iterables_without_consuming():
    supplied = statement(opening_liability=cash("0"), closing_liability=cash("10"))
    rows = (entry("0.01"),) * MAX_CARD_ENTRIES
    assert reconcile_card_statement(supplied, rows, coverage="complete").state == "matched"
    with pytest.raises(FinancialValueError):
        reconcile_card_statement(supplied, rows + (entry(),), coverage="complete")

    class Untrusted:
        def __iter__(self):
            raise AssertionError("Do not consume unbounded input")

    for value in (Untrusted(), list(rows), None, "private-input", True, (object(),)):
        with pytest.raises(FinancialValueError) as error:
            reconcile_card_statement(supplied, value, coverage="complete")
        assert "private-input" not in str(error.value)


@pytest.mark.parametrize(
    "factory,changes",
    [
        (statement, {"period_start": day("2026-10-16")}),
        (statement, {"period_end": "2026-10-15"}),
        (statement, {"statement_date": date(2026, 10, 15)}),
        (statement, {"due_date": True}),
        (statement, {"minimum_due": cash("-0.01")}),
        (current, {"credit_limit": cash("-0.01")}),
        (current, {"as_of_date": None}),
        (current, {"as_of_instant": "2026-10-20T00:00:00Z"}),
        (current, {"as_of_instant": FinancialInstant("2026-10-19T23:30:00-05:30")}),
        (entry, {"transaction_date": "2026-10-01"}),
        (entry, {"posting_date": True}),
        (entry, {"billing_amount": cash("-1")}),
        (entry, {"role": "pending_debit"}),
        (entry, {"role": "pending_credit"}),
        (entry, {"role": "unresolved"}),
        (entry, {"original_amount": cash("-1", "USD")}),
    ],
)
def test_normalization_contract_rejects_incompatible_dates_roles_and_magnitudes(factory, changes):
    with pytest.raises(FinancialValueError):
        factory(**changes)


@pytest.mark.parametrize(
    "factory,names",
    [
        (statement, ("opening_liability", "closing_liability", "total_due", "minimum_due")),
        (current, ("outstanding", "unbilled", "credit_limit", "available_credit")),
        (entry, ("billing_amount",)),
    ],
)
def test_native_fields_reject_currency_kind_and_primitive_coercion(factory, names):
    invalid = [
        cash("1", "USD"),
        FinancialValue("display_amount", "1", currency="INR"),
        1,
        1.5,
        True,
        None,
    ]
    for name in names:
        for value in invalid:
            with pytest.raises(FinancialValueError):
                factory(**{name: value})


@pytest.mark.parametrize("value", [False, [], {}, "private-input", "POSTED", 1])
def test_choice_fields_fail_with_fixed_messages(value):
    for operation in (
        lambda: entry(role=value),
        lambda: entry(treatment=value),
        lambda: reconcile_card_statement(statement(), (), coverage=value),
    ):
        with pytest.raises(FinancialValueError) as error:
            operation()
        assert str(error.value) == "Unsupported credit-card contract choice."


@pytest.mark.parametrize(
    "changes",
    [
        {"state": "unknown"},
        {"state": "unavailable", "reason": None},
        {"state": "unavailable", "reason": "missing_checkpoint", "difference": cash("0")},
        {"state": "matched", "reason": "missing_checkpoint"},
        {"state": "matched", "calculated_closing": None},
        {"state": "matched", "difference": cash(None)},
        {"state": "matched", "difference": cash("1")},
        {"state": "mismatched", "difference": cash("0")},
        {"state": "matched", "difference": cash("0", "USD")},
    ],
)
def test_result_cannot_claim_matching_or_partial_totals_in_invalid_states(changes):
    with pytest.raises(FinancialValueError):
        CardReconciliation(
            **(
                dict(
                    state="matched", reason=None, calculated_closing=cash("0"), difference=cash("0")
                )
                | changes
            )
        )


def test_private_frozen_contracts_contain_no_identity_narration_or_payment_status():
    result = reconcile_card_statement(statement(), (entry(),), coverage="complete")
    for value in (statement(), current(), entry(), result):
        assert not hasattr(value, "__dict__")
        assert "15000" not in repr(value) and "2026" not in repr(value)
        assert "5000" not in repr(value) and "12400" not in repr(value)
        name = fields(value)[0].name
        with pytest.raises(FrozenInstanceError):
            setattr(value, name, "private-input")
        assert not {field.name for field in fields(value)} & {
            "card_number",
            "last_four",
            "narration",
            "account_id",
            "source_id",
            "paid",
            "overdue",
        }
