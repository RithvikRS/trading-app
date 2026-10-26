"""Private finite credit identities and mapping history; no financial payloads."""

from typing import Any, Literal

from pydantic import Field, model_validator

from trading_api.evidence_read_contracts import HistoryQuery, Revision
from trading_api.read_contracts import FinancialPage, IdentityView, OpaqueIdentifier, WireModel


class CreditAccountView(IdentityView):
    issuer: Literal["hdfc"]
    billing_currency: Literal["INR"]
    label: str = Field(
        min_length=1, max_length=64, pattern=r"^[A-Za-z][A-Za-z .()-]{0,63}$", repr=False
    )
    revision: Revision
    state: Literal["active", "archived"]


class CreditSourceView(IdentityView):
    family: Literal["hdfc_credit_statement"]
    mapping_revision: Revision | None
    account_id: OpaqueIdentifier | None
    state: Literal["mapped", "unmapped", "archived"]

    @model_validator(mode="after")
    def mapping(self) -> CreditSourceView:
        if (self.account_id is None) != (self.state == "unmapped") or (
            self.account_id is not None and self.mapping_revision is None
        ):
            raise ValueError("Credit mapping is unavailable.")
        return self


class CreditPage[T: IdentityView](FinancialPage[T]):
    @model_validator(mode="after")
    def ordering(self) -> CreditPage[T]:
        ids = [item.id for item in self.items]
        if ids != sorted(set(ids)):
            raise ValueError("Credit page is unavailable.")
        return self


class CreditMappingView(WireModel):
    source_id: OpaqueIdentifier
    revision: Revision
    previous_revision: Revision | None
    account_id: OpaqueIdentifier | None
    reason: Literal["initial", "correction", "unlinked"]
    is_latest_revision: bool
    account_state: Literal["active", "archived"] | None

    @model_validator(mode="after")
    def history(self) -> CreditMappingView:
        if (
            self.previous_revision != (self.revision - 1 if self.revision > 1 else None)
            or (self.reason == "initial") != (self.revision == 1)
            or (self.reason == "unlinked") != (self.account_id is None)
            or (self.account_id is None) != (self.account_state is None)
        ):
            raise ValueError("Credit mapping history is unavailable.")
        return self


class CreditMappingHistoryQuery(HistoryQuery):
    pass


class CreditMappingHistoryPage(WireModel):
    items: tuple[CreditMappingView, ...] = Field(max_length=100, repr=False)
    next_before: Revision | None = None

    @model_validator(mode="after")
    def history(self) -> CreditMappingHistoryPage:
        if self.next_before is not None and (
            not self.items or self.next_before != self.items[-1].revision
        ):
            raise ValueError("Credit history continuation is unavailable.")
        if self.items:
            source = self.items[0].source_id
            for index, item in enumerate(self.items):
                if item.source_id != source or (
                    index
                    and (
                        item.revision != self.items[index - 1].revision - 1
                        or item.is_latest_revision
                    )
                ):
                    raise ValueError("Credit history ordering is unavailable.")
        return self


def private_payload(value: Any, *, depth: int = 0) -> Any:
    """Extract declared wire fields without invoking serializers on counterfeit models."""
    if depth > 4:
        raise ValueError("Credit response is unavailable.")
    if isinstance(value, WireModel):
        fields = set(type(value).model_fields)
        if (
            set(value.__dict__) != fields
            or value.__pydantic_extra__
            or value.__pydantic_private__
            or not value.model_fields_set <= fields
        ):
            raise ValueError("Credit response is unavailable.")
        return {name: private_payload(value.__dict__[name], depth=depth + 1) for name in fields}
    if type(value) is tuple and len(value) <= 100:
        return tuple(private_payload(item, depth=depth + 1) for item in value)
    if value is None or type(value) in (str, int, bool):
        return value
    raise ValueError("Credit response is unavailable.")


def serialize_response[T: WireModel](model: type[T], value: T) -> bytes:
    if type(value) is not model:
        raise ValueError("Credit response is unavailable.")
    checked = model.model_validate(private_payload(value))
    return checked.model_dump_json(warnings="error").encode()
