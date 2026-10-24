"""Dated source observations and explicit selection intent; no inferred valuation."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import AfterValidator, Field, model_validator

from trading_api.evidence_read_contracts import (
    Revision,
    RevisionView,
    SourceDate,
    SourceEvidenceView,
)
from trading_api.finance import FinancialInstant, MissingReason, ReportedMarketValue
from trading_api.read_contracts import IdentityView, OpaqueIdentifier, PageQuery, WireModel
from trading_db.market_contracts import MarketTarget


def source_instant(value: str) -> str:
    FinancialInstant(value)
    return value


type SourceInstant = Annotated[str, Field(max_length=32), AfterValidator(source_instant)]
type Currency = Literal["INR", "USD"]


class InspectQuery(WireModel):
    id: OpaqueIdentifier


class SnapshotQuery(PageQuery):
    account_id: OpaqueIdentifier


class MarketQuery(PageQuery):
    kind: Literal["quote", "nav", "fx"]
    instrument_id: OpaqueIdentifier | None = None

    @model_validator(mode="after")
    def scope(self) -> MarketQuery:
        if (self.kind == "fx") != (self.instrument_id is None):
            raise ValueError("Market scope requires its explicit instrument or currency kind.")
        return self


class ListingQuery(PageQuery):
    instrument_id: OpaqueIdentifier


class ListingView(IdentityView):
    instrument_id: OpaqueIdentifier
    venue: Literal["XNSE", "XBOM", "XNYS", "XNAS", "ARCX"]
    symbol: str = Field(min_length=1, max_length=32, repr=False)
    series: str = Field(max_length=8)
    quote_currency: Currency


class SnapshotView(SourceEvidenceView):
    position_id: OpaqueIdentifier | None
    instrument_id: OpaqueIdentifier | None
    currency: Currency | None
    kind: Literal["position_snapshot", "cash_snapshot"]
    correction_reason: Literal["source_correction", "cancellation", "reinstatement"] | None
    as_of_date: SourceDate | None = Field(repr=False)
    as_of_instant: SourceInstant | None = Field(repr=False)
    snapshot_scope: Literal["selected_position", "native_cash", "full_account"] | None
    reconciliation_boundary: Literal["before_period", "after_period"] | None
    booking_date: SourceDate | None = Field(repr=False)

    @model_validator(mode="after")
    def precision(self) -> SnapshotView:
        if self.as_of_instant is not None and self.as_of_date != self.as_of_instant[:10]:
            raise ValueError("Snapshot precision is unavailable.")
        return self


class SnapshotSelectionView(RevisionView):
    account_id: OpaqueIdentifier
    position_id: OpaqueIdentifier | None
    currency: Currency | None
    snapshot_id: OpaqueIdentifier | None
    snapshot_revision: Revision | None
    reason: Literal["reviewed", "newer_evidence", "correction", "clear"]

    @model_validator(mode="after")
    def choice(self) -> SnapshotSelectionView:
        if (self.snapshot_id is None) != (self.snapshot_revision is None):
            raise ValueError("Snapshot choice is unavailable.")
        if (self.reason == "clear") != (self.snapshot_id is None):
            raise ValueError("Snapshot choice is unavailable.")
        return self


class SnapshotResolution(WireModel):
    selection: SnapshotSelectionView
    state: Literal["selected", "unselected", "stale", "cancelled", "archived", "conflicting"]
    snapshot: SnapshotView | None = Field(repr=False)

    @model_validator(mode="after")
    def usable(self) -> SnapshotResolution:
        if not self.selection.is_current or (self.state == "selected") != (
            self.snapshot is not None
        ):
            raise ValueError("Snapshot resolution is unavailable.")
        if self.snapshot is not None and (
            self.snapshot.id != self.selection.snapshot_id
            or self.snapshot.revision != self.selection.snapshot_revision
            or self.snapshot.account_id != self.selection.account_id
            or self.snapshot.position_id != self.selection.position_id
            or self.snapshot.currency != self.selection.currency
            or not self.snapshot.is_current
            or self.snapshot.status != "active"
            or self.snapshot.account_state != "active"
        ):
            raise ValueError("Snapshot resolution is unavailable.")
        return self


class MarketIdentity(WireModel):
    kind: Literal["quote", "nav", "fx"]
    instrument_id: OpaqueIdentifier | None
    listing_id: OpaqueIdentifier | None
    currency: Currency | None
    base_currency: Currency | None
    quote_currency: Currency | None
    basis: Literal["close", "last", "nav", "reference", "spot"]

    @model_validator(mode="after")
    def target(self) -> MarketIdentity:
        fields = self.model_dump(include=set(MarketTarget.model_fields))
        for name in ("instrument_id", "listing_id"):
            fields[name] = UUID(fields[name]) if fields[name] else None
        MarketTarget.model_validate(fields)
        return self


class MarketObservationView(MarketIdentity, IdentityView):
    previous_id: OpaqueIdentifier | None
    is_current: bool
    adjustment: Literal["unadjusted", "split_adjusted", "unknown"] | None
    namespace: Literal[
        "manual_evidence", "amfi_nav_report", "exchange_quote_report", "fx_rate_report"
    ]
    observed_on: SourceDate = Field(repr=False)
    observed_at: SourceInstant | None = Field(repr=False)
    source: str | None = Field(max_length=32, repr=False)
    missing_reason: MissingReason | None
    usable: bool

    @model_validator(mode="after")
    def reported(self) -> MarketObservationView:
        value = ReportedMarketValue(
            "fx_rate" if self.kind == "fx" else "unit_price",
            self.source,
            currency=self.currency,
            base_currency=self.base_currency,
            quote_currency=self.quote_currency,
            missing_reason=self.missing_reason,
        )
        if (self.kind == "quote") != (self.adjustment is not None):
            raise ValueError("Market adjustment is unavailable.")
        if self.usable != (
            value.usable and (self.kind != "quote" or self.adjustment == "unadjusted")
        ):
            raise ValueError("Market usability is unavailable.")
        if self.observed_at is not None and self.observed_on != self.observed_at[:10]:
            raise ValueError("Market precision is unavailable.")
        return self


class MarketSelectionView(MarketIdentity, RevisionView):
    observation_id: OpaqueIdentifier | None
    reason: Literal["reviewed", "replacement", "correction", "clear"]

    @model_validator(mode="after")
    def choice(self) -> MarketSelectionView:
        if (self.reason == "clear") != (self.observation_id is None):
            raise ValueError("Market choice is unavailable.")
        return self


class MarketResolution(WireModel):
    selection: MarketSelectionView
    state: Literal["selected", "unselected", "stale", "unusable"]
    observation: MarketObservationView | None = Field(repr=False)

    @model_validator(mode="after")
    def usable(self) -> MarketResolution:
        if not self.selection.is_current or (self.state == "selected") != (
            self.observation is not None
        ):
            raise ValueError("Market resolution is unavailable.")
        if self.observation is not None and (
            self.observation.id != self.selection.observation_id
            or not self.observation.is_current
            or not self.observation.usable
            or self.observation.model_dump(include=set(MarketTarget.model_fields))
            != self.selection.model_dump(include=set(MarketTarget.model_fields))
        ):
            raise ValueError("Market resolution is unavailable.")
        return self
