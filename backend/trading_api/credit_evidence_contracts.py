"""Strict unselected credit evidence; native source strings remain authoritative."""

from typing import Annotated, Literal

from pydantic import AfterValidator, Field, model_validator

from trading_api.credit_cards import (
    CardCurrentValues,
    CardEntryValues,
    CardRole,
    CardStatementValues,
    CardTreatment,
)
from trading_api.evidence_read_contracts import HistoryQuery, Revision
from trading_api.finance import (
    Currency,
    FinancialDate,
    FinancialInstant,
    FinancialValue,
    MissingReason,
)
from trading_api.read_contracts import IdentityView, OpaqueIdentifier, PageQuery, WireModel

type CreditKind = Literal["statement", "current", "entry"]


def valid_day(value: str) -> str:
    FinancialDate(value)
    return value


def valid_instant(value: str) -> str:
    FinancialInstant(value)
    return value


type EvidenceDate = Annotated[str, Field(min_length=10, max_length=10), AfterValidator(valid_day)]
type EvidenceInstant = Annotated[
    str, Field(min_length=20, max_length=32), AfterValidator(valid_instant)
]


class CreditEvidenceQuery(PageQuery):
    account_id: OpaqueIdentifier
    kind: CreditKind


class CreditEvidenceHistoryQuery(HistoryQuery):
    account_id: OpaqueIdentifier
    kind: CreditKind


class CreditEvidenceInspectQuery(WireModel):
    account_id: OpaqueIdentifier
    kind: CreditKind
    id: OpaqueIdentifier
    at_revision: Revision


class CreditCashView(WireModel):
    source: str | None = Field(max_length=32, repr=False)
    currency: Currency
    missing_reason: MissingReason | None

    def cash(self) -> FinancialValue:
        return FinancialValue(
            "cash", self.source, currency=self.currency, missing_reason=self.missing_reason
        )

    @model_validator(mode="after")
    def exact(self) -> CreditCashView:
        self.cash()
        return self


class CreditStatementValuesView(WireModel):
    period_start: EvidenceDate = Field(repr=False)
    period_end: EvidenceDate = Field(repr=False)
    statement_date: EvidenceDate = Field(repr=False)
    due_date: EvidenceDate | None = Field(repr=False)
    opening_liability: CreditCashView = Field(repr=False)
    closing_liability: CreditCashView = Field(repr=False)
    total_due: CreditCashView = Field(repr=False)
    minimum_due: CreditCashView = Field(repr=False)

    @model_validator(mode="after")
    def exact(self) -> CreditStatementValuesView:
        CardStatementValues(
            FinancialDate(self.period_start),
            FinancialDate(self.period_end),
            FinancialDate(self.statement_date),
            FinancialDate(self.due_date) if self.due_date else None,
            self.opening_liability.cash(),
            self.closing_liability.cash(),
            self.total_due.cash(),
            self.minimum_due.cash(),
        )
        return self


class CreditCurrentValuesView(WireModel):
    as_of_date: EvidenceDate = Field(repr=False)
    as_of_instant: EvidenceInstant | None = Field(repr=False)
    outstanding: CreditCashView = Field(repr=False)
    unbilled: CreditCashView = Field(repr=False)
    credit_limit: CreditCashView = Field(repr=False)
    available_credit: CreditCashView = Field(repr=False)

    @model_validator(mode="after")
    def exact(self) -> CreditCurrentValuesView:
        CardCurrentValues(
            FinancialDate(self.as_of_date),
            FinancialInstant(self.as_of_instant) if self.as_of_instant else None,
            self.outstanding.cash(),
            self.unbilled.cash(),
            self.credit_limit.cash(),
            self.available_credit.cash(),
        )
        return self


class CreditEntryValuesView(WireModel):
    role: CardRole
    treatment: CardTreatment
    transaction_date: EvidenceDate | None = Field(repr=False)
    posting_date: EvidenceDate | None = Field(repr=False)
    billing_amount: CreditCashView = Field(repr=False)
    original_amount: CreditCashView | None = Field(repr=False)

    @model_validator(mode="after")
    def exact(self) -> CreditEntryValuesView:
        CardEntryValues(
            self.role,
            self.treatment,
            self.billing_amount.cash(),
            FinancialDate(self.transaction_date) if self.transaction_date else None,
            FinancialDate(self.posting_date) if self.posting_date else None,
            self.original_amount.cash() if self.original_amount is not None else None,
        )
        return self


class CreditEvidenceBase(IdentityView):
    revision: Revision
    previous_revision: Revision | None
    source_id: OpaqueIdentifier
    mapping_revision: Revision
    account_id: OpaqueIdentifier
    account_state: Literal["active", "archived"]
    is_latest_revision: bool

    @model_validator(mode="after")
    def predecessor(self) -> CreditEvidenceBase:
        if self.previous_revision != (self.revision - 1 if self.revision > 1 else None):
            raise ValueError("Credit evidence revision is unavailable.")
        return self


class CreditStatementView(CreditEvidenceBase):
    kind: Literal["statement"]
    values: CreditStatementValuesView = Field(repr=False)


class CreditCurrentView(CreditEvidenceBase):
    kind: Literal["current"]
    values: CreditCurrentValuesView = Field(repr=False)


class CreditEntryView(CreditEvidenceBase):
    kind: Literal["entry"]
    values: CreditEntryValuesView = Field(repr=False)


type CreditEvidenceView = Annotated[
    CreditStatementView | CreditCurrentView | CreditEntryView, Field(discriminator="kind")
]


def evidence_model(
    kind: CreditKind,
) -> type[CreditStatementView] | type[CreditCurrentView] | type[CreditEntryView]:
    if kind == "statement":
        return CreditStatementView
    if kind == "current":
        return CreditCurrentView
    return CreditEntryView


class CreditEvidencePage(WireModel):
    items: tuple[CreditEvidenceView, ...] = Field(max_length=100, repr=False)
    next_after: OpaqueIdentifier | None = None

    @model_validator(mode="after")
    def ordered(self) -> CreditEvidencePage:
        ids = [item.id for item in self.items]
        if ids != sorted(set(ids)) or (
            self.next_after is not None and (not ids or self.next_after != ids[-1])
        ):
            raise ValueError("Credit evidence page is unavailable.")
        if self.items and any(
            item.account_id != self.items[0].account_id
            or item.kind != self.items[0].kind
            or not item.is_latest_revision
            for item in self.items
        ):
            raise ValueError("Credit evidence scope is unavailable.")
        return self


class CreditEvidenceHistoryPage(WireModel):
    items: tuple[CreditEvidenceView, ...] = Field(max_length=100, repr=False)
    next_before: Revision | None = None

    @model_validator(mode="after")
    def ordered(self) -> CreditEvidenceHistoryPage:
        if self.next_before is not None and (
            not self.items or self.next_before != self.items[-1].revision
        ):
            raise ValueError("Credit evidence history continuation is unavailable.")
        if self.items:
            first = self.items[0]
            for index, item in enumerate(self.items):
                if (item.id, item.account_id, item.kind, item.source_id) != (
                    first.id,
                    first.account_id,
                    first.kind,
                    first.source_id,
                ) or (
                    index
                    and (
                        item.revision != self.items[index - 1].revision - 1
                        or item.is_latest_revision
                    )
                ):
                    raise ValueError("Credit evidence history is unavailable.")
        return self
