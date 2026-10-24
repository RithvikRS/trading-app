"""Exact market evidence contracts; no provider access or inferred freshness."""

from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from trading_api.finance import FinancialDate, FinancialInstant, MissingReason, ReportedMarketValue
from trading_db.instruments import Definition


class MarketTarget(Definition):
    kind: Literal["quote", "nav", "fx"]
    instrument_id: UUID | None = None
    listing_id: UUID | None = None
    currency: Literal["INR", "USD"] | None = None
    base_currency: Literal["INR", "USD"] | None = None
    quote_currency: Literal["INR", "USD"] | None = None
    basis: Literal["close", "last", "nav", "reference", "spot"]

    @model_validator(mode="after")
    def identity(self) -> MarketTarget:
        if self.instrument_id == UUID(int=0) or self.listing_id == UUID(int=0):
            raise ValueError("Market identity requires nonzero identifiers.")
        if self.kind == "fx":
            if (
                self.instrument_id is not None
                or self.listing_id is not None
                or self.currency is not None
                or self.base_currency is None
                or self.quote_currency is None
                or self.base_currency == self.quote_currency
                or self.basis not in {"reference", "spot"}
            ):
                raise ValueError("FX evidence requires an explicit directed pair and basis.")
        elif (
            self.instrument_id is None
            or self.currency is None
            or self.base_currency is not None
            or self.quote_currency is not None
            or (
                self.kind == "quote"
                and (self.listing_id is None or self.basis not in {"close", "last"})
            )
            or (
                self.kind == "nav"
                and (self.listing_id is not None or self.basis != "nav" or self.currency != "INR")
            )
        ):
            raise ValueError("Price evidence requires its exact instrument, listing and basis.")
        return self


class MarketDefinition(MarketTarget):
    previous_id: UUID | None = None
    adjustment: Literal["unadjusted", "split_adjusted", "unknown"] | None = None
    namespace: Literal[
        "manual_evidence", "amfi_nav_report", "exchange_quote_report", "fx_rate_report"
    ]
    digest_algorithm: Literal["sha256"] = "sha256"
    digest: str = Field(pattern=r"^[0-9a-f]{64}$", min_length=64, max_length=64, repr=False)
    occurrence: int = Field(ge=1, le=1000)
    normalizer: str = Field(pattern=r"^[a-z][a-z0-9_]{0,47}$", min_length=1, max_length=48)
    normalizer_version: int = Field(ge=1, le=9007199254740991)
    contract_version: Literal[1] = 1
    observed_on: str = Field(repr=False)
    observed_at: str | None = Field(default=None, repr=False)
    source: str | None = Field(repr=False)
    missing_reason: MissingReason | None = None

    @field_validator("contract_version", mode="before")
    @classmethod
    def version_type(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("Market contract version must be an integer.")
        return value

    @model_validator(mode="after")
    def evidence(self) -> MarketDefinition:
        if self.previous_id == UUID(int=0):
            raise ValueError("Correction identity is unavailable.")
        if (self.kind == "quote") != (self.adjustment is not None):
            raise ValueError("Only quote evidence requires an adjustment basis.")
        if (
            self.namespace != "manual_evidence"
            and self.namespace
            != {
                "quote": "exchange_quote_report",
                "nav": "amfi_nav_report",
                "fx": "fx_rate_report",
            }[self.kind]
        ):
            raise ValueError("Evidence source does not support this market kind.")
        FinancialDate(self.observed_on)
        if self.observed_at is not None:
            FinancialInstant(self.observed_at)
            if self.observed_at[:10] != self.observed_on:
                raise ValueError("Observation date must match the source-local timestamp date.")
        self.reported()
        return self

    def target(self) -> MarketTarget:
        return MarketTarget.model_validate(self.model_dump(include=set(MarketTarget.model_fields)))

    def reported(self) -> ReportedMarketValue:
        return ReportedMarketValue(
            "fx_rate" if self.kind == "fx" else "unit_price",
            self.source,
            currency=self.currency,
            base_currency=self.base_currency,
            quote_currency=self.quote_currency,
            missing_reason=self.missing_reason,
        )

    @property
    def usable(self) -> bool:
        return self.reported().usable and (self.kind != "quote" or self.adjustment == "unadjusted")
