"""Bounded normalized evidence; no parser, document storage or financial posting."""

from decimal import Decimal
from typing import Literal, cast
from uuid import UUID

from pydantic import Field, model_validator

from trading_api.finance import EvidenceMeaning, FinancialDate, FinancialValue
from trading_db.instruments import Definition

type CandidateKind = Literal[
    "cash_movement",
    "buy",
    "sell",
    "subscription",
    "redemption",
    "dividend",
    "fee",
    "withholding",
    "position_snapshot",
    "cash_snapshot",
    "lot_acquisition",
    "lot_remaining",
    "unsupported",
]
type ValueRole = Literal[
    "quantity",
    "net_cash",
    "gross_cash",
    "unit_price",
    "fee",
    "withholding",
    "acquisition_cost",
    "reported_tax_basis",
]
SECURITY_KINDS = {
    "buy",
    "sell",
    "subscription",
    "redemption",
    "dividend",
    "position_snapshot",
    "lot_acquisition",
    "lot_remaining",
}
SNAPSHOT_KINDS = {"position_snapshot", "cash_snapshot", "lot_acquisition", "lot_remaining"}
TRADE_KINDS = {"buy", "sell", "subscription", "redemption"}
COMPONENTS = {
    "cash_movement": {"net_cash", "fee", "withholding"},
    "cash_snapshot": {"net_cash"},
    "fee": {"net_cash"},
    "withholding": {"net_cash"},
    "dividend": {"net_cash", "gross_cash", "fee", "withholding"},
    **{
        kind: {"quantity", "net_cash", "gross_cash", "unit_price", "fee", "withholding"}
        for kind in TRADE_KINDS
    },
    **{
        kind: {
            "quantity",
            "unit_price",
            "acquisition_cost",
            "reported_tax_basis",
            "fee",
            "withholding",
        }
        for kind in ("position_snapshot", "lot_acquisition", "lot_remaining")
    },
}


class ObservationDefinition(Definition):
    digest: str = Field(pattern=r"^[0-9a-f]{64}$", repr=False)
    digest_algorithm: Literal["sha256_v1"] = "sha256_v1"
    period_start: str | None = Field(default=None, repr=False)
    period_end: str | None = Field(default=None, repr=False)
    coverage: Literal["complete_activity", "partial_activity", "snapshot", "unknown"]

    @model_validator(mode="after")
    def period(self) -> ObservationDefinition:
        if (self.period_start is None) != (self.period_end is None):
            raise ValueError("Source period requires both calendar dates.")
        if self.period_start is not None and self.period_end is not None:
            if FinancialDate(self.period_start).value > FinancialDate(self.period_end).value:
                raise ValueError("Source period is reversed.")
        elif self.coverage != "unknown":
            raise ValueError("Known coverage requires its supplied period.")
        return self


class StagedValue(Definition):
    role: ValueRole
    source: str | None = Field(repr=False)
    currency: Literal["INR", "USD"] | None = None
    missing_reason: (
        Literal["not_supplied", "incomplete_history", "unsupported", "conflicting_evidence"] | None
    ) = None

    def financial(self) -> FinancialValue:
        if self.role == "quantity":
            return FinancialValue(
                "quantity_movement",
                self.source,
                currency=self.currency,
                missing_reason=self.missing_reason,
            )
        if self.role in ("net_cash", "gross_cash"):
            return FinancialValue(
                "cash", self.source, currency=self.currency, missing_reason=self.missing_reason
            )
        if self.role == "unit_price":
            return FinancialValue(
                "unit_price",
                self.source,
                currency=self.currency,
                missing_reason=self.missing_reason,
            )
        return FinancialValue(
            "monetary_evidence",
            self.source,
            currency=self.currency,
            meaning=cast(EvidenceMeaning, self.role),
            missing_reason=self.missing_reason,
        )

    @model_validator(mode="after")
    def exact(self) -> StagedValue:
        self.financial()
        return self


class CandidateDefinition(Definition):
    occurrence: int = Field(ge=1, le=1_000_000)
    kind: CandidateKind
    instrument_identifier_id: UUID | None = None
    trade_date: str | None = Field(default=None, repr=False)
    settlement_date: str | None = Field(default=None, repr=False)
    booking_date: str | None = Field(default=None, repr=False)
    value_date: str | None = Field(default=None, repr=False)
    as_of_date: str | None = Field(default=None, repr=False)
    blocked_reason: Literal["not_supplied", "unsupported", "conflicting_evidence"] | None = None
    values: tuple[StagedValue, ...] = Field(default=(), max_length=8, repr=False)

    @model_validator(mode="after")
    def structure(self) -> CandidateDefinition:
        if self.instrument_identifier_id == UUID(int=0):
            raise ValueError("Invalid security reference.")
        for name in ("trade_date", "settlement_date", "booking_date", "value_date", "as_of_date"):
            value = getattr(self, name)
            if value is not None:
                FinancialDate(value)
        if len({value.role for value in self.values}) != len(self.values):
            raise ValueError("A source component cannot occur twice in a candidate.")
        return self

    def issue(self) -> str | None:
        """Review eligibility only; not reconciliation or permission to post."""
        if self.blocked_reason:
            return self.blocked_reason
        if self.kind == "unsupported":
            return "unsupported"
        if any(value.role not in COMPONENTS[self.kind] for value in self.values):
            return "unsupported_component"
        values: dict[str, Decimal | None] = {
            item.role: item.financial().value for item in self.values
        }
        required = {"net_cash"}
        if self.kind in TRADE_KINDS:
            required.add("quantity")
            supplied_date = self.trade_date
        elif self.kind in SNAPSHOT_KINDS:
            required = {"net_cash"} if self.kind == "cash_snapshot" else {"quantity"}
            supplied_date = self.as_of_date
        else:
            supplied_date = self.booking_date
        if supplied_date is None or any(values.get(role) is None for role in required):
            return "not_supplied"
        if self.kind in SECURITY_KINDS and self.instrument_identifier_id is None:
            return "unresolved_instrument"
        quantity, cash = values.get("quantity"), values.get("net_cash")
        if quantity is not None and (
            (self.kind in ("buy", "subscription") and quantity <= 0)
            or (self.kind in ("sell", "redemption") and quantity >= 0)
            or (self.kind in SNAPSHOT_KINDS and quantity < 0)
        ):
            return "conflicting_evidence"
        if cash is not None and (
            (self.kind in ("buy", "subscription") and cash >= 0)
            or (self.kind in ("sell", "redemption") and cash <= 0)
            or (self.kind == "dividend" and cash < 0)
            or (self.kind in ("fee", "withholding") and cash > 0)
        ):
            return "conflicting_evidence"
        return None


class BatchDefinition(Definition):
    normalizer: str = Field(min_length=1, max_length=48, pattern=r"^[a-z][a-z0-9_/-]*$")
    normalizer_version: str = Field(
        min_length=1, max_length=32, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$"
    )
    rows: tuple[CandidateDefinition, ...] = Field(min_length=1, max_length=100, repr=False)

    @model_validator(mode="after")
    def occurrences(self) -> BatchDefinition:
        if len({row.occurrence for row in self.rows}) != len(self.rows):
            raise ValueError("Each source occurrence must be unique within its batch.")
        if tuple(sorted(row.occurrence for row in self.rows)) != tuple(
            row.occurrence for row in self.rows
        ):
            raise ValueError("Source occurrences must be supplied in increasing order.")
        return self
