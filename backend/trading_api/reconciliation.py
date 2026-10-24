"""Conditional exact reconciliation of bounded evidence; no provenance or ownership assertion."""

from dataclasses import dataclass
from decimal import Decimal, DecimalException, localcontext
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from trading_api.finance import (
    Currency,
    FinancialDate,
    FinancialValue,
    FinancialValueError,
    MissingReason,
    _exact_context,
)

RULE_VERSION = 1
MAX_ACTIVITIES = 1000
type Outcome = Literal["balanced", "mismatch", "unavailable", "not_applicable"]
type Reason = Literal[
    "checkpoint_only",
    "incomplete_coverage",
    "baseline_unverified",
    "excluded_activity",
    "unresolved_components",
    "missing_checkpoints",
    "unknown_boundary",
    "checkpoint_period",
    "missing_values",
    "missing_activity_date",
    "activity_outside_period",
    "closing_mismatch",
]


class Contract(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )


class ReconciliationScope(Contract):
    kind: Literal["cash", "units"]
    account_id: UUID
    currency: Currency | None = None
    position_id: UUID | None = None

    @model_validator(mode="after")
    def identity(self) -> ReconciliationScope:
        if not self.account_id.int or self.position_id == UUID(int=0):
            raise ValueError("Reconciliation scope requires nonzero opaque identities.")
        if (self.kind == "cash" and (self.currency is None or self.position_id is not None)) or (
            self.kind == "units" and (self.currency is not None or self.position_id is None)
        ):
            raise ValueError("Reconciliation requires one native currency or one position.")
        return self


class ReconciliationPeriod(Contract):
    start: str = Field(repr=False)
    end: str = Field(repr=False)
    date_basis: Literal["booking", "value", "settlement", "trade"]

    @model_validator(mode="after")
    def dates(self) -> ReconciliationPeriod:
        if FinancialDate(self.start).value > FinancialDate(self.end).value:
            raise ValueError("Reconciliation period is reversed.")
        return self


class ScopedEvidence(Contract):
    scope: ReconciliationScope
    reference: UUID
    revision: int = Field(default=1, ge=1, le=9007199254740991)
    source: str | None = Field(repr=False)
    missing_reason: MissingReason | None = None

    def financial(self) -> FinancialValue:
        return FinancialValue(
            "cash" if self.scope.kind == "cash" else "quantity_movement",
            self.source,
            currency=self.scope.currency,
            missing_reason=self.missing_reason,
        )

    @model_validator(mode="after")
    def exact(self) -> ScopedEvidence:
        if not self.reference.int:
            raise ValueError("Evidence requires a nonzero opaque reference.")
        self.financial()
        return self


class ReconciliationCheckpoint(ScopedEvidence):
    date: str = Field(repr=False)
    boundary: Literal["before_period", "after_period", "unknown"]

    @model_validator(mode="after")
    def checkpoint(self) -> ReconciliationCheckpoint:
        FinancialDate(self.date)
        if self.scope.kind == "units":
            FinancialValue("position_quantity", self.source, missing_reason=self.missing_reason)
        return self


class ReconciliationActivity(ScopedEvidence):
    date: str | None = Field(repr=False)
    posting_state: Literal["posted", "pending"]

    @model_validator(mode="after")
    def activity_date(self) -> ReconciliationActivity:
        if self.date is not None:
            FinancialDate(self.date)
        return self


class LedgerEvidence(Contract):
    side: Literal["source", "combined"]
    scope: ReconciliationScope
    period: ReconciliationPeriod
    coverage: Literal["complete_activity", "partial_activity", "unknown", "snapshot"]
    opening: ReconciliationCheckpoint | None = Field(default=None, repr=False)
    closing: ReconciliationCheckpoint | None = Field(default=None, repr=False)
    activities: tuple[ReconciliationActivity, ...] = Field(
        default=(), max_length=MAX_ACTIVITIES, repr=False
    )
    unresolved_components: bool = False
    excluded_source_count: int = Field(default=0, ge=0, le=MAX_ACTIVITIES)
    baseline_verified: bool = False

    @model_validator(mode="after")
    def coherent(self) -> LedgerEvidence:
        if (self.scope.kind == "units") != (self.period.date_basis == "trade"):
            raise ValueError("Date basis does not describe this native ledger scope.")
        if self.side == "source" and (self.baseline_verified or self.excluded_source_count):
            raise ValueError("Source reconciliation includes every supplied activity.")
        if self.coverage == "snapshot" and self.activities:
            raise ValueError("Snapshot-only evidence cannot declare activity coverage.")
        evidence = [*self.activities]
        checkpoints = [item for item in (self.opening, self.closing) if item is not None]
        if any(item.scope != self.scope for item in (*evidence, *checkpoints)):
            raise ValueError("Reconciliation cannot mix accounts, currencies or positions.")
        references = [item.reference for item in (*evidence, *checkpoints)]
        if len(set(references)) != len(references):
            raise ValueError("An evidence reference cannot count twice in one reconciliation.")
        return self


@dataclass(frozen=True, repr=False)
class ReconciliationResult:
    evidence: LedgerEvidence
    outcome: Outcome
    reasons: tuple[Reason, ...]
    posted_count: int
    pending_count: int
    posted_total: str | None = None
    calculated_closing: str | None = None
    difference: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "rule_version": RULE_VERSION,
            "evidence": self.evidence.model_dump(mode="json"),
            "outcome": self.outcome,
            "reasons": list(self.reasons),
            "posted_count": self.posted_count,
            "pending_count": self.pending_count,
            "posted_total": self.posted_total,
            "calculated_closing": self.calculated_closing,
            "difference": self.difference,
        }


def reconcile(evidence: LedgerEvidence) -> ReconciliationResult:
    if not isinstance(evidence, LedgerEvidence):
        raise FinancialValueError("Reconciliation requires typed evidence.")
    # Revalidate constructed/copied models, including every nested value and scope.
    valid = LedgerEvidence.model_validate(evidence)
    posted = tuple(item for item in valid.activities if item.posting_state == "posted")
    posted_count, pending_count = len(posted), len(valid.activities) - len(posted)
    if valid.coverage == "snapshot":
        return ReconciliationResult(
            valid, "not_applicable", ("checkpoint_only",), posted_count, pending_count
        )
    reasons: list[Reason] = []
    if valid.coverage != "complete_activity":
        reasons.append("incomplete_coverage")
    if valid.side == "combined" and not valid.baseline_verified:
        reasons.append("baseline_unverified")
    if valid.excluded_source_count:
        reasons.append("excluded_activity")
    if valid.unresolved_components:
        reasons.append("unresolved_components")
    if valid.opening is None or valid.closing is None:
        reasons.append("missing_checkpoints")
    else:
        if (valid.opening.boundary, valid.closing.boundary) != ("before_period", "after_period"):
            reasons.append("unknown_boundary")
        if (valid.opening.date, valid.closing.date) != (valid.period.start, valid.period.end):
            reasons.append("checkpoint_period")
    values = (*posted, *(item for item in (valid.opening, valid.closing) if item is not None))
    if any(item.source is None for item in values):
        reasons.append("missing_values")
    if any(item.date is None for item in posted):
        reasons.append("missing_activity_date")
    if any(
        item.date is not None and not valid.period.start <= item.date <= valid.period.end
        for item in posted
    ):
        reasons.append("activity_outside_period")
    if reasons:
        return ReconciliationResult(
            valid, "unavailable", tuple(reasons), posted_count, pending_count
        )
    assert valid.opening is not None and valid.closing is not None
    opening, closing = valid.opening.financial().value, valid.closing.financial().value
    assert opening is not None and closing is not None
    try:
        with localcontext(_exact_context()):
            total = Decimal("0")
            for item in posted:
                amount = item.financial().value
                assert amount is not None
                total += amount
            calculated = opening + total
            difference = calculated - closing
            # 1,000 bounded native movements plus two checkpoints stay below this
            # derived bound even when an intermediate sum exceeds an individual amount.
            if any(
                value.copy_abs() >= Decimal("1e22") for value in (total, calculated, difference)
            ):
                raise FinancialValueError("Reconciliation exceeds its derived amount bound.")
    except DecimalException:
        raise FinancialValueError("Reconciliation could not be performed exactly.") from None
    return ReconciliationResult(
        valid,
        "balanced" if difference == 0 else "mismatch",
        () if difference == 0 else ("closing_mismatch",),
        posted_count,
        pending_count,
        posted_total=format(total, "f"),
        calculated_closing=format(calculated, "f"),
        difference=format(difference, "f"),
    )


@dataclass(frozen=True, repr=False)
class ReconciliationPair:
    source: ReconciliationResult
    combined: ReconciliationResult
    reasons: tuple[Literal["checkpoint_conflict"], ...] = ()

    @property
    def balanced(self) -> bool:
        return not self.reasons and self.source.outcome == self.combined.outcome == "balanced"

    def to_dict(self) -> dict[str, object]:
        return {
            "rule_version": RULE_VERSION,
            "source": self.source.to_dict(),
            "combined": self.combined.to_dict(),
            "balanced": self.balanced,
            "reasons": list(self.reasons),
        }


def reconcile_pair(source: LedgerEvidence, combined: LedgerEvidence) -> ReconciliationPair:
    source_result, combined_result = reconcile(source), reconcile(combined)
    left, right = source_result.evidence, combined_result.evidence
    if (
        left.side != "source"
        or right.side != "combined"
        or (left.scope != right.scope or left.period != right.period)
    ):
        raise FinancialValueError("Reconciliation views require the same scope and period.")
    conflict = any(
        first is not None
        and second is not None
        and first.source is not None
        and second.source is not None
        and first.financial().value != second.financial().value
        for first, second in ((left.opening, right.opening), (left.closing, right.closing))
    )
    return ReconciliationPair(
        source_result, combined_result, ("checkpoint_conflict",) if conflict else ()
    )
