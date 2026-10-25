"""Pure credit-card liability values; no source format, identity, or persistence."""

from dataclasses import dataclass
from typing import Literal

from trading_api.finance import (
    FinancialDate,
    FinancialInstant,
    FinancialValue,
    FinancialValueError,
    sum_cash,
)

MAX_CARD_ENTRIES = 1000

type CardRole = Literal[
    "posted_debit", "posted_credit", "pending_debit", "pending_credit", "unresolved"
]
type CardTreatment = Literal["movement", "ambiguous", "unsupported"]
type CardCoverage = Literal["complete", "partial", "unknown"]
type ReconciliationState = Literal["matched", "mismatched", "unavailable"]
type ReconciliationReason = Literal[
    "incomplete_coverage",
    "unknown_coverage",
    "missing_checkpoint",
    "unresolved_entry",
    "ambiguous_entry",
    "unsupported_entry",
    "missing_posting_date",
    "missing_billing_amount",
    "outside_period",
    "arithmetic_bounds",
]

_ROLES = {"posted_debit", "posted_credit", "pending_debit", "pending_credit", "unresolved"}
_TREATMENTS = {"movement", "ambiguous", "unsupported"}
_REASONS = {
    "incomplete_coverage",
    "unknown_coverage",
    "missing_checkpoint",
    "unresolved_entry",
    "ambiguous_entry",
    "unsupported_entry",
    "missing_posting_date",
    "missing_billing_amount",
    "outside_period",
    "arithmetic_bounds",
}


def _choice(value: object, choices: set[str]) -> None:
    if type(value) is not str or value not in choices:
        raise FinancialValueError("Unsupported credit-card contract choice.")


def _amount(value: FinancialValue, *, original: bool = False, nonnegative: bool = False) -> None:
    if type(value) is not FinancialValue or value.kind != "cash":
        raise FinancialValueError("Credit-card amounts require exact native monetary values.")
    if not original and value.currency != "INR":
        raise FinancialValueError("Credit-card billing values require INR.")
    if nonnegative and value.value is not None and value.value < 0:
        raise FinancialValueError("This credit-card value requires a nonnegative magnitude.")


def _day(value: FinancialDate | None, *, optional: bool = False) -> None:
    if value is None and optional:
        return
    if type(value) is not FinancialDate:
        raise FinancialValueError("Credit-card dates require exact financial dates.")


@dataclass(frozen=True, slots=True, repr=False)
class CardStatementValues:
    """Independent source checkpoints; signed balances are not movement entries."""

    period_start: FinancialDate
    period_end: FinancialDate
    statement_date: FinancialDate
    due_date: FinancialDate | None
    opening_liability: FinancialValue
    closing_liability: FinancialValue
    total_due: FinancialValue
    minimum_due: FinancialValue

    def __post_init__(self) -> None:
        for value in (self.period_start, self.period_end, self.statement_date):
            _day(value)
        _day(self.due_date, optional=True)
        if self.period_start.value > self.period_end.value:
            raise FinancialValueError("A billing period requires ordered dates.")
        for amount in (self.opening_liability, self.closing_liability, self.total_due):
            _amount(amount)
        _amount(self.minimum_due, nonnegative=True)


@dataclass(frozen=True, slots=True, repr=False)
class CardCurrentValues:
    """Separately dated source evidence, never inferred from statement activity."""

    as_of_date: FinancialDate
    as_of_instant: FinancialInstant | None
    outstanding: FinancialValue
    unbilled: FinancialValue
    credit_limit: FinancialValue
    available_credit: FinancialValue

    def __post_init__(self) -> None:
        _day(self.as_of_date)
        if self.as_of_instant is not None:
            if type(self.as_of_instant) is not FinancialInstant:
                raise FinancialValueError("Current credit evidence requires an exact instant.")
            if self.as_of_instant.source[:10] != self.as_of_date.source:
                raise FinancialValueError("Current evidence date must match its source-local day.")
        for amount in (self.outstanding, self.unbilled, self.available_credit):
            _amount(amount)
        _amount(self.credit_limit, nonnegative=True)


@dataclass(frozen=True, slots=True, repr=False)
class CardEntryValues:
    """Explicit normalized direction, magnitude, dates and interpretation.

    A role is a caller classification, not an interpretation of an issuer label.
    Original-currency evidence has no implied relation to the billed magnitude.
    """

    role: CardRole
    treatment: CardTreatment
    billing_amount: FinancialValue
    transaction_date: FinancialDate | None
    posting_date: FinancialDate | None
    original_amount: FinancialValue | None = None

    def __post_init__(self) -> None:
        _choice(self.role, _ROLES)
        _choice(self.treatment, _TREATMENTS)
        _amount(self.billing_amount, nonnegative=True)
        _day(self.transaction_date, optional=True)
        _day(self.posting_date, optional=True)
        if self.original_amount is not None:
            _amount(self.original_amount, original=True, nonnegative=True)
        if self.role in {"pending_debit", "pending_credit"} and self.posting_date is not None:
            raise FinancialValueError("A pending entry cannot have a posting date.")
        if self.role == "unresolved" and self.treatment == "movement":
            raise FinancialValueError("An unresolved entry cannot claim supported treatment.")


@dataclass(frozen=True, slots=True, repr=False)
class CardReconciliation:
    """Arithmetic outcome only; matching never establishes coverage or payment."""

    state: ReconciliationState
    reason: ReconciliationReason | None
    calculated_closing: FinancialValue | None
    difference: FinancialValue | None

    def __post_init__(self) -> None:
        _choice(self.state, {"matched", "mismatched", "unavailable"})
        if self.state == "unavailable":
            _choice(self.reason, _REASONS)
            if self.calculated_closing is not None or self.difference is not None:
                raise FinancialValueError("Unavailable reconciliation cannot expose totals.")
        else:
            if self.reason is not None:
                raise FinancialValueError(
                    "Calculated reconciliation cannot have an absence reason."
                )
            for amount in (self.calculated_closing, self.difference):
                if amount is None:
                    raise FinancialValueError("Reconciliation requires known totals.")
                _amount(amount)
                if amount.value is None:
                    raise FinancialValueError("Reconciliation requires known totals.")
            if self.difference is None or (
                (self.difference.value == 0) != (self.state == "matched")
            ):
                raise FinancialValueError("Reconciliation state must agree with the difference.")


def _unavailable(reason: ReconciliationReason) -> CardReconciliation:
    return CardReconciliation("unavailable", reason, None, None)


def _opposite(value: FinancialValue) -> FinancialValue:
    if value.value is None:
        raise FinancialValueError("Reconciliation requires a known amount.")
    # copy_negate is exact even under hostile ambient Decimal precision/traps.
    return FinancialValue("cash", format(value.value.copy_negate(), "f"), currency="INR")


def reconcile_card_statement(
    statement: CardStatementValues,
    entries: tuple[CardEntryValues, ...],
    *,
    coverage: CardCoverage,
) -> CardReconciliation:
    """Compare one bounded caller-supplied statement scope without deduplicating it."""
    if type(statement) is not CardStatementValues:
        raise FinancialValueError("Reconciliation requires a credit-card statement.")
    if type(entries) is not tuple or len(entries) > MAX_CARD_ENTRIES:
        raise FinancialValueError("Reconciliation requires a bounded immutable entry collection.")
    if any(type(entry) is not CardEntryValues for entry in entries):
        raise FinancialValueError("Reconciliation requires credit-card entry values.")
    _choice(coverage, {"complete", "partial", "unknown"})
    if coverage == "partial":
        return _unavailable("incomplete_coverage")
    if coverage == "unknown":
        return _unavailable("unknown_coverage")
    if statement.opening_liability.value is None or statement.closing_liability.value is None:
        return _unavailable("missing_checkpoint")

    movements = [statement.opening_liability]
    for entry in entries:
        if entry.role in {"pending_debit", "pending_credit"}:
            continue
        if entry.role == "unresolved":
            return _unavailable("unresolved_entry")
        if entry.treatment == "ambiguous":
            return _unavailable("ambiguous_entry")
        if entry.treatment == "unsupported":
            return _unavailable("unsupported_entry")
        if entry.posting_date is None:
            return _unavailable("missing_posting_date")
        if (
            not statement.period_start.value
            <= entry.posting_date.value
            <= statement.period_end.value
        ):
            return _unavailable("outside_period")
        if entry.billing_amount.value is None:
            return _unavailable("missing_billing_amount")
        movements.append(
            _opposite(entry.billing_amount)
            if entry.role == "posted_credit"
            else entry.billing_amount
        )
    try:
        calculated = sum_cash(movements, currency="INR")
        difference = sum_cash((statement.closing_liability, _opposite(calculated)), currency="INR")
    except FinancialValueError:
        return _unavailable("arithmetic_bounds")
    return CardReconciliation(
        "matched" if difference.value == 0 else "mismatched", None, calculated, difference
    )
