"""Finite declarations and immutable confirmations for owner-entered bank identities."""

from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from trading_api.read_contracts import OpaqueIdentifier, WireModel

MAX_SETUPS = 1000
CURRENCIES = (("INR",), ("USD",), ("INR", "USD"))


class BankDeclaration(WireModel):
    institution: Literal["hdfc", "sbi"]
    label: str = Field(pattern=r"^[A-Za-z][A-Za-z .()-]{0,63}$", repr=False)
    currencies: tuple[Literal["INR", "USD"], ...] = Field(min_length=1, max_length=2)

    @field_validator("currencies", mode="before")
    @classmethod
    def json_currencies(cls, value: Any) -> Any:
        # JSON arrays have a single explicit normalization; scalar/item coercion stays off.
        return tuple(value) if type(value) is list else value

    @model_validator(mode="after")
    def canonical_currencies(self) -> BankDeclaration:
        if self.currencies not in CURRENCIES:
            raise ValueError("Expected canonical declared currencies.")
        return self


class BankSetupQuery(WireModel):
    pass


class BankSetupCommand(BankDeclaration):
    intent_id: OpaqueIdentifier
    expected_revision: int = Field(ge=0, le=MAX_SETUPS)


class BankSetupReceipt(BankDeclaration):
    intent_id: OpaqueIdentifier
    revision: int = Field(ge=1, le=MAX_SETUPS)
    account_id: OpaqueIdentifier


class BankSetupHead(WireModel):
    revision: int = Field(ge=0, le=MAX_SETUPS)
    last_saved: BankSetupReceipt | None

    @model_validator(mode="after")
    def consistent_head(self) -> BankSetupHead:
        if (self.revision == 0) != (self.last_saved is None) or (
            self.last_saved is not None and self.last_saved.revision != self.revision
        ):
            raise ValueError("Inconsistent setup head.")
        return self
