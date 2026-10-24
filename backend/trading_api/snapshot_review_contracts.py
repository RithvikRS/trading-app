"""Explicit snapshot review commands; no client ownership or inferred identities."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, model_validator

from trading_api.evidence_read_contracts import Revision
from trading_api.import_read_contracts import BatchView, ImportRowView
from trading_api.read_contracts import (
    InstrumentView,
    OpaqueIdentifier,
    PositionView,
    WireModel,
)
from trading_api.receipt_read_contracts import ReceiptView
from trading_api.valuation_read_contracts import SnapshotResolution
from trading_db.completion_contracts import CompletionRequest, CompletionRow, CompletionSelection

type ExpectedRevision = Annotated[int, Field(ge=0, le=9007199254740991)]


class AccountMappingCommand(WireModel):
    source_id: OpaqueIdentifier
    account_id: OpaqueIdentifier
    expected_revision: ExpectedRevision


class InstrumentMappingCommand(WireModel):
    identifier_id: OpaqueIdentifier
    instrument_id: OpaqueIdentifier
    listing_id: OpaqueIdentifier | None = None
    expected_revision: ExpectedRevision


class PositionCommand(WireModel):
    account_id: OpaqueIdentifier
    instrument_id: OpaqueIdentifier
    holding_form: Literal["demat", "folio", "custody"]


class DecisionCommand(WireModel):
    row_id: OpaqueIdentifier
    action: Literal["include", "exclude", "reopen"]
    expected_revision: ExpectedRevision


class SnapshotDirective(WireModel):
    row_id: OpaqueIdentifier
    review_revision: Revision
    operation: Literal["record", "correct", "exclude"]
    position_id: OpaqueIdentifier | None = None
    target_id: OpaqueIdentifier | None = None
    target_revision: Revision | None = None
    correction_reason: Literal["source_correction", "cancellation", "reinstatement"] | None = None
    select: bool = False
    selection_revision: ExpectedRevision = 0

    def completion_row(self) -> CompletionRow:
        return CompletionRow(
            row_id=UUID(self.row_id),
            review_revision=self.review_revision,
            operation=self.operation,
            position_id=UUID(self.position_id) if self.position_id else None,
            target_kind="snapshot" if self.operation == "correct" else None,
            target_id=UUID(self.target_id) if self.target_id else None,
            target_revision=self.target_revision,
            correction_reason=self.correction_reason,
        )

    @model_validator(mode="after")
    def shape(self) -> SnapshotDirective:
        self.completion_row()
        if (self.operation == "exclude" and self.select) or (
            not self.select and self.selection_revision != 0
        ):
            raise ValueError("Snapshot selection requires an included row.")
        return self


class PreviewCommand(WireModel):
    idempotency_key: OpaqueIdentifier
    batch_id: OpaqueIdentifier
    batch_revision: Revision
    rows: list[SnapshotDirective] = Field(min_length=1, max_length=100, repr=False)

    def completion(self, baseline: str) -> CompletionRequest:
        return CompletionRequest(
            idempotency_key=UUID(self.idempotency_key),
            batch_id=UUID(self.batch_id),
            batch_revision=self.batch_revision,
            baseline=baseline,
            mode="limited",
            rows=tuple(row.completion_row() for row in self.rows),
            selections=tuple(
                CompletionSelection(
                    row_id=UUID(row.row_id),
                    expected_revision=row.selection_revision,
                    reason="correction" if row.operation == "correct" else "reviewed",
                )
                for row in self.rows
                if row.select
            ),
        )

    @model_validator(mode="after")
    def whole_manifest(self) -> PreviewCommand:
        self.completion("0" * 64)
        return self


class CompleteCommand(WireModel):
    token: str = Field(min_length=1, max_length=100000, repr=False)


class PreviewView(CompleteCommand):
    batch_id: OpaqueIdentifier
    batch_revision: Revision
    row_count: int = Field(ge=1, le=100)
    selection_count: int = Field(ge=0, le=100)
    expires_in: Literal[300] = 300
    coverage: Literal["snapshot"] = "snapshot"


class MappingView(WireModel):
    row_id: OpaqueIdentifier
    instrument_id: OpaqueIdentifier | None
    listing_id: OpaqueIdentifier | None
    revision: ExpectedRevision


class ReviewInspection(WireModel):
    batch: BatchView
    account_id: OpaqueIdentifier | None
    account_mapping_revision: ExpectedRevision
    rows: tuple[ImportRowView, ...] = Field(max_length=100, repr=False)
    mappings: tuple[MappingView, ...] = Field(max_length=100, repr=False)
    receipt: ReceiptView | None


class InvestmentView(PositionView):
    instrument: InstrumentView
    choices: tuple[SnapshotResolution, ...] = Field(max_length=3, repr=False)
