"""Finite wire contracts for authenticated financial identity reads."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator


def canonical_identifier(value: str) -> str:
    parsed = UUID(value)
    if not parsed.int or str(parsed) != value:
        raise ValueError("Expected a canonical nonzero opaque identifier.")
    return value


type OpaqueIdentifier = Annotated[
    str,
    Field(min_length=36, max_length=36),
    AfterValidator(canonical_identifier),
]


class WireModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )


class PageQuery(WireModel):
    limit: int = Field(default=25, ge=1, le=100)
    after: OpaqueIdentifier | None = None


class PositionQuery(PageQuery):
    account_id: OpaqueIdentifier


class IdentityView(WireModel):
    id: OpaqueIdentifier


class AccountView(IdentityView):
    kind: Literal["bank", "brokerage", "mutual_fund", "employee_stock"]
    institution: Literal["hdfc", "sbi", "indmoney", "fund_registrar", "ubs"]
    market: Literal["IN", "US"]
    label: str = Field(min_length=1, max_length=64, repr=False)
    currencies: tuple[Literal["INR", "USD"], ...] = Field(min_length=1, max_length=2)
    revision: int = Field(ge=1, le=9007199254740991)
    state: Literal["active", "archived"]


class SourceView(IdentityView):
    namespace: Literal[
        "hdfc_statement",
        "sbi_statement",
        "indmoney_india",
        "indmoney_us",
        "indmoney_funds",
        "cas",
        "advisor",
        "ubs_espp",
    ]
    mapping_revision: int | None = Field(ge=1, le=9007199254740991)
    account_id: OpaqueIdentifier | None
    state: Literal["mapped", "unmapped", "archived"]

    @model_validator(mode="after")
    def mapping(self) -> SourceView:
        if (self.account_id is None) != (self.state == "unmapped") or (
            self.account_id is not None and self.mapping_revision is None
        ):
            raise ValueError("Source mapping is unavailable.")
        return self


class InstrumentView(IdentityView):
    name: str = Field(min_length=1, max_length=120, repr=False)
    isin: str = Field(min_length=12, max_length=12, repr=False)
    asset_class: Literal["equity", "etf", "mutual_fund"]
    fund_scheme_id: OpaqueIdentifier | None
    fund_plan: Literal["direct", "regular"] | None
    fund_option: Literal["growth", "idcw_payout", "idcw_reinvestment"] | None
    fund_currency: Literal["INR"] | None

    @model_validator(mode="after")
    def variant(self) -> InstrumentView:
        fields = (
            self.fund_scheme_id,
            self.fund_plan,
            self.fund_option,
            self.fund_currency,
        )
        if (self.asset_class == "mutual_fund" and any(value is None for value in fields)) or (
            self.asset_class != "mutual_fund" and any(value is not None for value in fields)
        ):
            raise ValueError("Instrument variant is unavailable.")
        return self


class PositionView(IdentityView):
    account_id: OpaqueIdentifier
    instrument_id: OpaqueIdentifier
    holding_form: Literal["demat", "folio", "custody"]
    account_state: Literal["active", "archived"]


class FinancialPage[T: IdentityView](WireModel):
    items: tuple[T, ...] = Field(max_length=100, repr=False)
    next_after: OpaqueIdentifier | None = None

    @model_validator(mode="after")
    def cursor(self) -> FinancialPage[T]:
        if self.next_after is not None and (not self.items or self.items[-1].id != self.next_after):
            raise ValueError("Pagination reference is unavailable.")
        return self
