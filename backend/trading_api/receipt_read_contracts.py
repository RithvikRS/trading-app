"""Immutable completion evidence, distinct from current portfolio state."""

from decimal import Decimal, localcontext
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from trading_api.evidence_read_contracts import Revision, SourceDate
from trading_api.finance import FinancialValue, _exact_context
from trading_api.import_read_contracts import Coverage
from trading_api.read_contracts import IdentityView, OpaqueIdentifier, PageQuery, WireModel
from trading_api.reconciliation import ReconciliationPeriod, ReconciliationScope
from trading_api.valuation_read_contracts import SourceInstant


class ReceiptQuery(PageQuery):
    batch_id: OpaqueIdentifier | None = None


class ReceiptChildrenQuery(PageQuery):
    receipt_id: OpaqueIdentifier


class ReceiptView(IdentityView):
    batch_id: OpaqueIdentifier
    batch_revision: Revision
    mode: Literal["limited", "reconciled"]
    coverage: Coverage
    created_at: SourceInstant = Field(repr=False)
    row_count: int = Field(ge=1, le=100)
    selection_count: int = Field(ge=0, le=100)
    scope_count: int = Field(ge=0, le=100)

    @model_validator(mode="after")
    def coverage_mode(self) -> ReceiptView:
        if (self.mode == "reconciled") != (self.coverage == "complete_activity") or (
            (self.mode == "reconciled") != (self.scope_count > 0)
        ):
            raise ValueError("Completion coverage is unavailable.")
        return self


class CompletedRowView(IdentityView):
    receipt_id: OpaqueIdentifier
    review_revision: Revision
    operation: Literal["record", "correct", "exclude"]
    outcome: Literal["recorded", "linked", "corrected", "excluded"]
    event_id: OpaqueIdentifier | None
    lot_observation_id: OpaqueIdentifier | None
    snapshot_id: OpaqueIdentifier | None
    record_revision: Revision | None
    provider_identity_id: OpaqueIdentifier | None
    selection_id: OpaqueIdentifier | None
    selection_revision: Revision | None

    @model_validator(mode="after")
    def effect(self) -> CompletedRowView:
        targets = (self.event_id, self.lot_observation_id, self.snapshot_id)
        if self.operation == "exclude":
            if self.outcome != "excluded" or any(
                value is not None
                for value in (
                    *targets,
                    self.record_revision,
                    self.provider_identity_id,
                    self.selection_id,
                    self.selection_revision,
                )
            ):
                raise ValueError("Completed exclusion is unavailable.")
        elif (
            self.record_revision is None
            or sum(item is not None for item in targets) != 1
            or (self.operation == "record" and self.outcome not in {"recorded", "linked"})
            or (self.operation == "correct" and self.outcome != "corrected")
        ):
            raise ValueError("Completed effect is unavailable.")
        if self.provider_identity_id is not None and (
            self.event_id is None or self.operation != "record"
        ):
            raise ValueError("Completed provider link is unavailable.")
        if (self.selection_id is None) != (self.selection_revision is None) or (
            self.selection_id is not None and self.snapshot_id is None
        ):
            raise ValueError("Completed selection is unavailable.")
        return self


class ScopeView(IdentityView):
    receipt_id: OpaqueIdentifier
    kind: Literal["cash", "units"]
    account_id: OpaqueIdentifier
    position_id: OpaqueIdentifier | None
    currency: Literal["INR", "USD"] | None
    period_start: SourceDate = Field(repr=False)
    period_end: SourceDate = Field(repr=False)
    date_basis: Literal["booking", "value", "settlement", "trade"]
    rule_version: Literal[1]
    input_count: int = Field(ge=4, le=1000)

    @model_validator(mode="after")
    def scope(self) -> ScopeView:
        ReconciliationScope.model_validate(
            dict(
                kind=self.kind,
                account_id=UUID(self.account_id),
                position_id=UUID(self.position_id) if self.position_id else None,
                currency=self.currency,
            )
        )
        ReconciliationPeriod.model_validate(
            dict(
                start=self.period_start,
                end=self.period_end,
                date_basis=self.date_basis,
            )
        )
        if (self.kind == "units") != (self.date_basis == "trade"):
            raise ValueError("Native comparison scope is unavailable.")
        return self


class ComparisonSide(WireModel):
    outcome: Literal["balanced"]
    opening: str = Field(max_length=32, repr=False)
    closing: str = Field(max_length=32, repr=False)
    posted_total: str = Field(max_length=36, pattern=r"^-?(0|[1-9][0-9]*)(\.[0-9]+)?$", repr=False)
    calculated_closing: str = Field(
        max_length=36, pattern=r"^-?(0|[1-9][0-9]*)(\.[0-9]+)?$", repr=False
    )
    difference: str = Field(max_length=36, pattern=r"^-?(0|[1-9][0-9]*)(\.[0-9]+)?$", repr=False)
    posted_count: int = Field(ge=0, le=1000)
    pending_count: int = Field(ge=0, le=1000)


class ScopeInspection(WireModel):
    scope: ScopeView
    source: ComparisonSide = Field(repr=False)
    combined: ComparisonSide = Field(repr=False)

    @model_validator(mode="after")
    def comparison(self) -> ScopeInspection:
        for side in (self.source, self.combined):
            for value in (side.opening, side.closing):
                FinancialValue(
                    "cash" if self.scope.kind == "cash" else "position_quantity",
                    value,
                    currency=self.scope.currency,
                )
            for value in (side.posted_total, side.calculated_closing, side.difference):
                decimal = Decimal(value)
                if decimal.copy_abs() >= Decimal("1e22") or len(value.partition(".")[2]) > (
                    2 if self.scope.kind == "cash" else 12
                ):
                    raise ValueError("Comparison precision is unavailable.")
            if Decimal(side.difference) != 0 or Decimal(side.calculated_closing) != Decimal(
                side.closing
            ):
                raise ValueError("Completed comparison is unavailable.")
            with localcontext(_exact_context()):
                if Decimal(side.opening) + Decimal(side.posted_total) != Decimal(side.closing):
                    raise ValueError("Completed equation is unavailable.")
        if (Decimal(self.source.opening), Decimal(self.source.closing)) != (
            Decimal(self.combined.opening),
            Decimal(self.combined.closing),
        ) or self.source.posted_count + self.source.pending_count > 100:
            raise ValueError("Comparison boundary is unavailable.")
        if self.scope.input_count != 4 + sum(
            side.posted_count + side.pending_count for side in (self.source, self.combined)
        ):
            raise ValueError("Comparison input count is unavailable.")
        return self


class InputQuery(PageQuery):
    scope_id: OpaqueIdentifier
    side: Literal["source", "combined"]
    part: Literal["opening", "activity", "closing"]


class ComparisonInputView(IdentityView):
    scope_id: OpaqueIdentifier
    side: Literal["source", "combined"]
    part: Literal["opening", "activity", "closing"]
    reference_revision: Revision
    source_row_id: OpaqueIdentifier | None
    event_id: OpaqueIdentifier | None
    snapshot_id: OpaqueIdentifier | None
    source: str = Field(max_length=32, repr=False)
    evidence_date: SourceDate | None = Field(repr=False)
    posting_state: Literal["posted", "pending"] | None
    kind: Literal["cash", "units"]
    currency: Literal["INR", "USD"] | None

    @model_validator(mode="after")
    def evidence(self) -> ComparisonInputView:
        FinancialValue(
            "cash"
            if self.kind == "cash"
            else "quantity_movement"
            if self.part == "activity"
            else "position_quantity",
            self.source,
            currency=self.currency,
        )
        if (self.kind == "cash") != (self.currency is not None):
            raise ValueError("Input currency is unavailable.")
        if self.side == "source":
            valid = self.source_row_id == self.id and self.event_id is self.snapshot_id is None
        elif self.part == "activity":
            valid = self.event_id == self.id and self.source_row_id is self.snapshot_id is None
        else:
            valid = self.snapshot_id == self.id and self.source_row_id is self.event_id is None
        if (
            not valid
            or (self.part == "activity") != (self.posting_state is not None)
            or (self.part != "activity" and self.evidence_date is None)
        ):
            raise ValueError("Frozen input lineage is unavailable.")
        return self
