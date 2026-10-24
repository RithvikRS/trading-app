"""Bounded financial evidence responses preserve exact supplied values and history."""

from typing import Annotated, Literal

from pydantic import AfterValidator, Field, model_validator

from trading_api.finance import FinancialDate, MissingReason
from trading_api.read_contracts import (
    IdentityView,
    OpaqueIdentifier,
    PageQuery,
    WireModel,
)
from trading_db.import_contracts import StagedValue, ValueRole

MAX_REVISION = 9007199254740991


def calendar_date(value: str) -> str:
    FinancialDate(value)
    return value


type SourceDate = Annotated[str, Field(min_length=10, max_length=10), AfterValidator(calendar_date)]
type Revision = Annotated[int, Field(ge=1, le=MAX_REVISION)]


class EventQuery(PageQuery):
    account_id: OpaqueIdentifier


class LotQuery(PageQuery):
    position_id: OpaqueIdentifier


class LotObservationQuery(PageQuery):
    lot_id: OpaqueIdentifier


class HistoryQuery(WireModel):
    id: OpaqueIdentifier
    limit: int = Field(default=25, ge=1, le=100)
    before: Revision | None = None


class FinancialComponent(WireModel):
    role: ValueRole
    source: str | None = Field(max_length=32, repr=False)
    currency: Literal["INR", "USD"] | None
    missing_reason: MissingReason | None

    @model_validator(mode="after")
    def exact(self) -> FinancialComponent:
        StagedValue.model_validate(self.model_dump())
        return self


class RevisionView(IdentityView):
    revision: Revision
    is_current: bool


class SourceEvidenceView(RevisionView):
    source_row_id: OpaqueIdentifier
    source_review_revision: Revision
    source_id: OpaqueIdentifier
    observation_id: OpaqueIdentifier
    batch_id: OpaqueIdentifier
    coverage: Literal["complete_activity", "partial_activity", "snapshot", "unknown"]
    period_start: SourceDate | None = Field(repr=False)
    period_end: SourceDate | None = Field(repr=False)
    cash_date_basis: Literal["booking", "value", "settlement"] | None
    account_id: OpaqueIdentifier
    account_state: Literal["active", "archived"]
    status: Literal["active", "cancelled"]
    components: tuple[FinancialComponent, ...] = Field(max_length=8, repr=False)

    @model_validator(mode="after")
    def evidence(self) -> SourceEvidenceView:
        if (
            (self.period_start is None) != (self.period_end is None)
            or (self.coverage != "unknown" and self.period_start is None)
            or (
                self.period_start is not None
                and self.period_end is not None
                and self.period_start > self.period_end
            )
        ):
            raise ValueError("Source coverage is unavailable.")
        roles = [value.role for value in self.components]
        if len(roles) != len(set(roles)) or (self.status == "cancelled" and self.components):
            raise ValueError("Financial evidence components are unavailable.")
        if self.status == "active" and not self.components:
            raise ValueError("Active financial evidence is unavailable.")
        return self


class EventView(SourceEvidenceView):
    position_id: OpaqueIdentifier | None
    instrument_id: OpaqueIdentifier | None
    correction_reason: (
        Literal["source_correction", "posting_update", "cancellation", "reinstatement"] | None
    )
    kind: Literal[
        "buy",
        "sell",
        "subscription",
        "redemption",
        "dividend",
        "fee",
        "withholding",
        "cash_movement",
    ]
    posting_state: Literal["posted", "pending"]
    trade_date: SourceDate | None = Field(repr=False)
    settlement_date: SourceDate | None = Field(repr=False)
    booking_date: SourceDate | None = Field(repr=False)
    value_date: SourceDate | None = Field(repr=False)


class LotView(IdentityView):
    position_id: OpaqueIdentifier
    account_id: OpaqueIdentifier
    instrument_id: OpaqueIdentifier
    account_state: Literal["active", "archived"]


class LotObservationView(SourceEvidenceView):
    lot_id: OpaqueIdentifier
    position_id: OpaqueIdentifier
    instrument_id: OpaqueIdentifier
    scope: Literal["lot_acquisition", "lot_remaining"]
    correction_reason: Literal["source_correction", "cancellation", "reinstatement"] | None
    as_of_date: SourceDate | None = Field(repr=False)
    acquisition_date: SourceDate | None = Field(repr=False)
    booking_date: SourceDate | None = Field(repr=False)


class HistoryPage[T: RevisionView](WireModel):
    items: tuple[T, ...] = Field(max_length=100, repr=False)
    next_before: Revision | None = None

    @model_validator(mode="after")
    def cursor(self) -> HistoryPage[T]:
        if self.next_before is not None and (
            not self.items or self.items[-1].revision != self.next_before
        ):
            raise ValueError("History pagination is unavailable.")
        return self
