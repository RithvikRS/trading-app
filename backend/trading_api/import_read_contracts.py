"""Import evidence and review intent do not imply completed financial effects."""

from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from trading_api.evidence_read_contracts import (
    FinancialComponent,
    Revision,
    RevisionView,
    SourceDate,
)
from trading_api.read_contracts import IdentityView, OpaqueIdentifier, PageQuery, WireModel
from trading_api.valuation_read_contracts import SourceInstant
from trading_db.import_contracts import CandidateDefinition, CandidateKind

type Coverage = Literal["complete_activity", "partial_activity", "snapshot", "unknown"]
type Issue = Literal[
    "not_supplied",
    "unsupported",
    "conflicting_evidence",
    "unsupported_component",
    "unresolved_instrument",
    "unresolved_account",
    "unsupported_currency",
    "incompatible_instrument",
    "stale_mapping",
    "revised_evidence",
]


class ObservationQuery(PageQuery):
    source_id: OpaqueIdentifier


class BatchQuery(WireModel):
    observation_id: OpaqueIdentifier
    limit: int = Field(default=25, ge=1, le=100)
    before: Revision | None = None


class RowQuery(WireModel):
    batch_id: OpaqueIdentifier
    limit: int = Field(default=25, ge=1, le=100)
    after_occurrence: int | None = Field(default=None, ge=1, le=1_000_000)


class SourceObservationView(IdentityView):
    source_id: OpaqueIdentifier
    previous_id: OpaqueIdentifier | None
    is_current: bool
    coverage: Coverage
    period_start: SourceDate | None = Field(repr=False)
    period_end: SourceDate | None = Field(repr=False)

    @model_validator(mode="after")
    def period(self) -> SourceObservationView:
        if (
            (self.period_start is None) != (self.period_end is None)
            or (self.coverage != "unknown" and self.period_start is None)
            or (
                self.period_start is not None
                and self.period_end is not None
                and self.period_start > self.period_end
            )
        ):
            raise ValueError("Source period is unavailable.")
        return self


class BatchView(RevisionView):
    observation_id: OpaqueIdentifier
    source_id: OpaqueIdentifier
    source_current: bool
    normalizer: str = Field(min_length=1, max_length=48, pattern=r"^[a-z][a-z0-9_/-]*$")
    normalizer_version: str = Field(
        min_length=1, max_length=32, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$"
    )
    contract_version: int = Field(ge=1, le=5)
    row_count: int = Field(ge=1, le=100)
    cash_date_basis: Literal["booking", "value", "settlement"] | None


class ReviewView(RevisionView):
    action: Literal["include", "exclude", "reopen"]
    reason: Literal["reviewed", "user_excluded", "duplicate_suspected", "reopened"]
    source_id: OpaqueIdentifier
    account_mapping_revision: Revision | None
    instrument_identifier_id: OpaqueIdentifier | None
    instrument_mapping_revision: Revision | None

    @model_validator(mode="after")
    def intent(self) -> ReviewView:
        if self.action == "include":
            if self.reason != "reviewed" or self.account_mapping_revision is None:
                raise ValueError("Review context is unavailable.")
            if (self.instrument_identifier_id is None) != (
                self.instrument_mapping_revision is None
            ):
                raise ValueError("Review context is unavailable.")
        elif (
            self.account_mapping_revision is not None
            or self.instrument_mapping_revision is not None
            or (
                self.action == "exclude"
                and self.reason not in {"user_excluded", "duplicate_suspected"}
            )
            or (self.action == "reopen" and self.reason != "reopened")
        ):
            raise ValueError("Review context is unavailable.")
        return self


class ImportRowView(IdentityView):
    batch_id: OpaqueIdentifier
    occurrence: int = Field(ge=1, le=1_000_000)
    kind: CandidateKind
    posting_state: Literal["posted", "pending"] | None
    instrument_identifier_id: OpaqueIdentifier | None
    trade_date: SourceDate | None = Field(repr=False)
    settlement_date: SourceDate | None = Field(repr=False)
    booking_date: SourceDate | None = Field(repr=False)
    value_date: SourceDate | None = Field(repr=False)
    as_of_date: SourceDate | None = Field(repr=False)
    acquisition_date: SourceDate | None = Field(repr=False)
    as_of_instant: SourceInstant | None = Field(repr=False)
    snapshot_scope: Literal["selected_position", "native_cash", "full_account"] | None
    reconciliation_boundary: Literal["before_period", "after_period"] | None
    blocked_reason: Literal["not_supplied", "unsupported", "conflicting_evidence"] | None
    components: tuple[FinancialComponent, ...] = Field(max_length=8, repr=False)
    status: Literal["included", "reviewable", "blocked", "excluded", "superseded"]
    issue: Issue | None
    decision: ReviewView | None = Field(repr=False)

    @model_validator(mode="after")
    def structure(self) -> ImportRowView:
        fields = self.model_dump(
            include={
                "occurrence",
                "kind",
                "posting_state",
                "instrument_identifier_id",
                "trade_date",
                "settlement_date",
                "booking_date",
                "value_date",
                "as_of_date",
                "acquisition_date",
                "as_of_instant",
                "snapshot_scope",
                "reconciliation_boundary",
                "blocked_reason",
            }
        )
        fields["instrument_identifier_id"] = (
            UUID(self.instrument_identifier_id) if self.instrument_identifier_id else None
        )
        fields["values"] = tuple(value.model_dump() for value in self.components)
        CandidateDefinition.model_validate(fields)
        if self.decision is not None and (
            self.decision.id != self.id or not self.decision.is_current
        ):
            raise ValueError("Current review is unavailable.")
        action = self.decision.action if self.decision else None
        if (
            (self.status == "superseded" and self.issue != "revised_evidence")
            or (self.issue == "revised_evidence" and self.status != "superseded")
            or (self.status == "blocked" and self.issue is None)
            or (self.status in {"included", "reviewable", "excluded"} and self.issue is not None)
            or (self.status == "included" and action != "include")
            or (self.status == "excluded" and action != "exclude")
            or (self.status == "reviewable" and action not in {None, "reopen"})
        ):
            raise ValueError("Effective review state is unavailable.")
        return self


class RowPage(WireModel):
    items: tuple[ImportRowView, ...] = Field(max_length=100, repr=False)
    next_after_occurrence: int | None = Field(default=None, ge=1, le=1_000_000)

    @model_validator(mode="after")
    def cursor(self) -> RowPage:
        if self.next_after_occurrence is not None and (
            not self.items or self.items[-1].occurrence != self.next_after_occurrence
        ):
            raise ValueError("Source occurrence pagination is unavailable.")
        return self
