"""Independent native-ledger examples and incomplete-evidence boundary cases."""

import json
from decimal import ROUND_DOWN, Inexact, Rounded, localcontext
from fractions import Fraction
from uuid import uuid4

import pytest
from pydantic import ValidationError

from trading_api.finance import FinancialValueError
from trading_api.reconciliation import (
    LedgerEvidence,
    ReconciliationActivity,
    ReconciliationCheckpoint,
    ReconciliationPeriod,
    ReconciliationScope,
    reconcile,
    reconcile_pair,
)


def scope(kind="cash", currency="INR"):
    return ReconciliationScope(
        kind=kind,
        account_id=uuid4(),
        currency=currency if kind == "cash" else None,
        position_id=uuid4() if kind == "units" else None,
    )


def checkpoint(target, value, boundary, **changes):
    fields = dict(
        scope=target,
        reference=uuid4(),
        source=value,
        boundary=boundary,
        date="2026-10-01" if boundary == "before_period" else "2026-10-31",
    )
    return ReconciliationCheckpoint(**(fields | changes))


def activity(target, value, **changes):
    return ReconciliationActivity(
        **(
            dict(
                scope=target,
                reference=uuid4(),
                source=value,
                date="2026-10-14",
                posting_state="posted",
            )
            | changes
        )
    )


def ledger(target=None, **changes):
    target = target or scope()
    return LedgerEvidence(
        **(
            dict(
                side="source",
                scope=target,
                period=ReconciliationPeriod(
                    start="2026-10-01",
                    end="2026-10-31",
                    date_basis="trade" if target.kind == "units" else "booking",
                ),
                coverage="complete_activity",
                opening=checkpoint(target, "100.00", "before_period"),
                closing=checkpoint(target, "125.00", "after_period"),
                activities=(activity(target, "50.00"), activity(target, "-25.00")),
            )
            | changes
        )
    )


@pytest.mark.parametrize("currency", ["INR", "USD"])
def test_known_cash_equation_preserves_original_values_and_excludes_pending(currency):
    target = scope(currency=currency)
    original = ledger(target)
    original = original.model_copy(
        update={
            "activities": (
                *original.activities,
                activity(
                    target, None, missing_reason="not_supplied", posting_state="pending", date=None
                ),
            )
        }
    )
    result = reconcile(original)
    assert result.outcome == "balanced" and result.reasons == ()
    assert result.posted_total == "25.00" and result.calculated_closing == "125.00"
    assert Fraction(result.difference) == 0
    assert (result.posted_count, result.pending_count) == (2, 1)
    payload = json.loads(json.dumps(result.to_dict(), allow_nan=False))
    assert payload["rule_version"] == 1
    assert payload["evidence"]["opening"]["source"] == "100.00"
    assert payload["evidence"]["activities"][2]["source"] is None
    assert payload["evidence"]["activities"][2]["missing_reason"] == "not_supplied"
    assert isinstance(payload["calculated_closing"], str)
    assert "125.00" not in repr(result) and "2026-10-01" not in repr(original)


def test_fractional_units_are_exact_under_hostile_ambient_decimal_context():
    target = scope("units")
    value = ledger(
        target,
        opening=checkpoint(target, "0.000000000001", "before_period"),
        closing=checkpoint(target, "1.234567890123", "after_period"),
        activities=(activity(target, "1.234567890124"), activity(target, "-0.000000000002")),
    )
    with localcontext() as context:
        context.prec = 2
        context.rounding = ROUND_DOWN
        context.traps[Inexact] = True
        context.traps[Rounded] = True
        result = reconcile(value)
    assert result.outcome == "balanced"
    assert Fraction(result.calculated_closing) == Fraction("1.234567890123")
    assert Fraction(result.posted_total) == Fraction("1.234567890124") - Fraction("0.000000000002")


def test_source_and_combined_state_must_both_balance():
    source = ledger()
    combined = source.model_copy(
        update={
            "side": "combined",
            "baseline_verified": True,
            "activities": (source.activities[0],),
        }
    )
    result = reconcile_pair(source, combined)
    assert result.source.outcome == "balanced"
    assert result.combined.outcome == "mismatch" and result.combined.difference == "25.00"
    assert not result.balanced
    assert reconcile_pair(
        source, source.model_copy(update={"side": "combined", "baseline_verified": True})
    ).balanced


@pytest.mark.parametrize(
    "changes,reason",
    [
        (dict(coverage="partial_activity"), "incomplete_coverage"),
        (dict(coverage="unknown"), "incomplete_coverage"),
        (dict(unresolved_components=True), "unresolved_components"),
        (dict(opening=None), "missing_checkpoints"),
        (dict(closing=None), "missing_checkpoints"),
        (dict(side="combined"), "baseline_unverified"),
        (
            dict(side="combined", baseline_verified=True, excluded_source_count=1),
            "excluded_activity",
        ),
    ],
)
def test_coinciding_amounts_cannot_hide_incomplete_evidence(changes, reason):
    result = reconcile(ledger().model_copy(update=changes))
    assert result.outcome == "unavailable" and reason in result.reasons
    assert result.posted_total is result.calculated_closing is result.difference is None


def test_missing_values_do_not_become_zero_and_explicit_zero_can_balance():
    target = scope()
    complete = ledger(
        target,
        opening=checkpoint(target, "0.00", "before_period"),
        closing=checkpoint(target, "0.00", "after_period"),
        activities=(),
    )
    assert reconcile(complete).outcome == "balanced"
    for key in ("opening", "closing"):
        checkpoint_value = getattr(complete, key).model_copy(
            update={"source": None, "missing_reason": "not_supplied"}
        )
        result = reconcile(complete.model_copy(update={key: checkpoint_value}))
        assert result.outcome == "unavailable" and "missing_values" in result.reasons
    result = reconcile(
        complete.model_copy(
            update={"activities": (activity(target, None, missing_reason="incomplete_history"),)}
        )
    )
    assert result.outcome == "unavailable" and result.posted_count == 1


@pytest.mark.parametrize(
    "field,changes,reason",
    [
        ("opening", dict(boundary="unknown"), "unknown_boundary"),
        ("closing", dict(boundary="before_period"), "unknown_boundary"),
        ("opening", dict(date="2026-09-30"), "checkpoint_period"),
        ("closing", dict(date="2026-11-01"), "checkpoint_period"),
    ],
)
def test_date_alone_cannot_invent_statement_boundary(field, changes, reason):
    value = ledger()
    result = reconcile(
        value.model_copy(update={field: getattr(value, field).model_copy(update=changes)})
    )
    assert result.outcome == "unavailable" and reason in result.reasons


@pytest.mark.parametrize(
    "date,reason",
    [
        (None, "missing_activity_date"),
        ("2026-09-30", "activity_outside_period"),
        ("2026-11-01", "activity_outside_period"),
    ],
)
def test_posted_activity_outside_known_calendar_scope_is_not_silently_dropped(date, reason):
    value = ledger()
    changed = value.activities[0].model_copy(update={"date": date})
    result = reconcile(value.model_copy(update={"activities": (changed, value.activities[1])}))
    assert result.outcome == "unavailable" and reason in result.reasons


def test_snapshot_only_is_not_a_complete_ledger():
    source = ledger(coverage="snapshot", activities=())
    combined = source.model_copy(update={"side": "combined"})
    result = reconcile_pair(source, combined)
    assert result.source.outcome == result.combined.outcome == "not_applicable"
    assert result.source.reasons == ("checkpoint_only",) and not result.balanced
    with pytest.raises(ValidationError):
        ledger(coverage="snapshot")


def test_a_confirmed_empty_complete_period_does_not_infer_missing_activity():
    target = scope()
    value = ledger(target, closing=checkpoint(target, "100.00", "after_period"), activities=())
    result = reconcile(value)
    assert result.outcome == "balanced" and result.posted_count == 0 and result.posted_total == "0"
    assert reconcile(value.model_copy(update={"coverage": "unknown"})).outcome == "unavailable"


def test_derived_sum_can_exceed_individual_amount_bound_without_rounding():
    target = scope()
    amount = "999999999999999999.99"
    value = ledger(
        target,
        opening=checkpoint(target, "0.00", "before_period"),
        closing=checkpoint(target, "0.00", "after_period"),
        activities=tuple(activity(target, amount) for _ in range(1000)),
    )
    result = reconcile(value)
    assert result.outcome == "mismatch"
    assert Fraction(result.posted_total) == 1000 * Fraction(amount)
    assert Fraction(result.difference) == 1000 * Fraction(amount)
    with pytest.raises(ValidationError):
        reconcile(
            value.model_copy(update={"activities": (*value.activities, activity(target, "1"))})
        )


def test_mixed_accounts_currencies_and_positions_are_rejected_before_arithmetic():
    value = ledger()
    for target in (scope(), scope(currency="USD"), scope("units")):
        with pytest.raises(ValidationError):
            reconcile(value.model_copy(update={"activities": (activity(target, "1"),)}))
    units = ledger(scope("units"))
    foreign = units.scope.model_copy(update={"position_id": uuid4()})
    with pytest.raises(ValidationError):
        reconcile(units.model_copy(update={"opening": checkpoint(foreign, "1", "before_period")}))


def test_duplicate_evidence_and_wrong_pair_scope_are_rejected():
    value = ledger()
    for updates in (
        dict(activities=(value.activities[0],) * 2),
        dict(closing=value.closing.model_copy(update={"reference": value.opening.reference})),
    ):
        with pytest.raises(ValidationError):
            reconcile(value.model_copy(update=updates))
    with pytest.raises(FinancialValueError):
        reconcile_pair(value, ledger(side="combined", baseline_verified=True))
    with pytest.raises(FinancialValueError):
        reconcile_pair(value, value)


@pytest.mark.parametrize("source", [1, 1.1, True, "1e2", "NaN", "1,000", "01", "0.001", "1" * 33])
def test_hostile_cash_values_fail_with_private_errors(source):
    with pytest.raises((ValidationError, FinancialValueError)):
        activity(scope(), source)


@pytest.mark.parametrize(
    "changes",
    [
        dict(baseline_verified="true"),
        dict(excluded_source_count=True),
        dict(excluded_source_count=1001),
        dict(side="source", excluded_source_count=1),
        dict(side="source", baseline_verified=True),
        dict(owner_id=uuid4()),
    ],
)
def test_flags_and_owner_injection_do_not_coerce(changes):
    with pytest.raises(ValidationError):
        ledger(**changes)


def test_constructed_nested_models_and_ambiguous_dates_are_revalidated():
    value = ledger()
    broken = value.activities[0].model_copy(update={"source": 1.1})
    with pytest.raises(ValidationError):
        reconcile(value.model_copy(update={"activities": (broken,)}))
    for changes in (
        dict(start="2026-10-01T00:00:00Z"),
        dict(end="2026-09-30"),
        dict(start="2026-02-30"),
    ):
        with pytest.raises(ValidationError):
            reconcile(value.model_copy(update={"period": value.period.model_copy(update=changes)}))
    with pytest.raises(ValidationError):
        reconcile(
            value.model_copy(
                update={"scope": value.scope.model_copy(update={"account_id": UUID_ZERO})}
            )
        )


UUID_ZERO = type(uuid4())(int=0)


def test_separately_balanced_views_cannot_disagree_on_absolute_checkpoints():
    source = ledger()
    combined = source.model_copy(
        update={
            "side": "combined",
            "baseline_verified": True,
            "opening": checkpoint(source.scope, "200.00", "before_period"),
            "closing": checkpoint(source.scope, "225.00", "after_period"),
        }
    )
    result = reconcile_pair(source, combined)
    assert result.source.outcome == result.combined.outcome == "balanced"
    assert not result.balanced and result.reasons == ("checkpoint_conflict",)
    payload = result.to_dict()
    assert payload["balanced"] is False and payload["reasons"] == ["checkpoint_conflict"]
    same = source.model_copy(
        update={
            "side": "combined",
            "baseline_verified": True,
            "opening": checkpoint(source.scope, "100.0", "before_period"),
            "closing": checkpoint(source.scope, "125", "after_period"),
        }
    )
    assert reconcile_pair(source, same).balanced
