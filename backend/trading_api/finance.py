"""Exact, bounded financial primitives; no persistence, HTTP, or provider access."""

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import (
    ROUND_HALF_UP,
    Clamped,
    Context,
    Decimal,
    DecimalException,
    DivisionByZero,
    FloatOperation,
    Inexact,
    InvalidOperation,
    Overflow,
    Rounded,
    Subnormal,
    Underflow,
    localcontext,
)
from typing import Literal

type Currency = Literal["INR", "USD"]
type ValueKind = Literal[
    "cash",
    "monetary_evidence",
    "quantity_movement",
    "position_quantity",
    "lot_quantity",
    "unit_price",
    "fx_rate",
    "display_amount",
]
type EvidenceMeaning = Literal["acquisition_cost", "reported_tax_basis", "fee", "withholding"]
type MissingReason = Literal[
    "not_supplied", "incomplete_history", "unsupported", "conflicting_evidence"
]

MAX_SOURCE_LENGTH = 32  # Sign + 18 integer digits + point + 12 fractional digits.
MAX_SUM_ITEMS = 10_000
_LIMIT = Decimal("1000000000000000000")
_MINOR_UNIT = Decimal("0.01")
_NUMBER = re.compile(r"-?(?:0|[1-9][0-9]{0,17})(?:\.[0-9]{1,12})?")
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_INSTANT = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.(?P<fraction>[0-9]{1,6}))?(?P<offset>Z|[+-][0-9]{2}:[0-9]{2})"
)
_SCALES = {
    "cash": 2,
    "monetary_evidence": 8,
    "quantity_movement": 12,
    "position_quantity": 12,
    "lot_quantity": 12,
    "unit_price": 12,
    "fx_rate": 12,
    "display_amount": 2,
}
_MONEY_KINDS = {"cash", "monetary_evidence", "unit_price", "display_amount"}
_QUANTITY_KINDS = {"quantity_movement", "position_quantity", "lot_quantity"}
_REASONS = {"not_supplied", "incomplete_history", "unsupported", "conflicting_evidence"}
_MEANINGS = {"acquisition_cost", "reported_tax_basis", "fee", "withholding"}


class FinancialValueError(ValueError):
    """Messages contain only fixed contract descriptions, never supplied values."""


def _currency(value: object) -> None:
    if type(value) is not str or value not in {"INR", "USD"}:
        raise FinancialValueError("Unsupported currency.")


def _parse_number(source: str, kind: ValueKind) -> Decimal:
    if type(source) is not str or len(source) > MAX_SOURCE_LENGTH or not _NUMBER.fullmatch(source):
        raise FinancialValueError("Expected a bounded plain decimal string.")
    fractional = source.partition(".")[2]
    if len(fractional) > _SCALES[kind]:
        raise FinancialValueError("Value exceeds the permitted fractional precision.")
    value = Decimal(source)  # Exact construction; independent of the ambient context.
    if value.copy_abs() >= _LIMIT:
        raise FinancialValueError("Value exceeds the permitted magnitude.")
    if kind in {"unit_price", "fx_rate"} and value <= 0:
        raise FinancialValueError("A usable price or rate must be positive.")
    if kind in {"position_quantity", "lot_quantity"} and value < 0:
        raise FinancialValueError("A long position or lot quantity cannot be negative.")
    return value.copy_abs() if value.is_zero() else value


@dataclass(frozen=True, slots=True)
class FinancialValue:
    """A typed value or explicit absence, with its original representation retained.

    Quantity kinds denote security units; the containing position/event supplies
    instrument identity. Unit prices are currency per security unit. An FX rate
    means quote-currency units per one base-currency unit.
    """

    kind: ValueKind
    source: str | None = field(repr=False)
    currency: Currency | None = None
    meaning: EvidenceMeaning | None = None
    base_currency: Currency | None = None
    quote_currency: Currency | None = None
    missing_reason: MissingReason | None = None
    value: Decimal | None = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if type(self.kind) is not str or self.kind not in _SCALES:
            raise FinancialValueError("Unsupported financial value kind.")
        if self.kind in _MONEY_KINDS:
            _currency(self.currency)
        elif self.currency is not None:
            raise FinancialValueError("This value kind does not take a currency.")
        if self.kind == "fx_rate":
            _currency(self.base_currency)
            _currency(self.quote_currency)
            if self.base_currency == self.quote_currency:
                raise FinancialValueError("An FX rate requires distinct currencies.")
        elif self.base_currency is not None or self.quote_currency is not None:
            raise FinancialValueError("Only an FX rate takes a currency pair.")
        if self.kind == "monetary_evidence":
            if type(self.meaning) is not str or self.meaning not in _MEANINGS:
                raise FinancialValueError("Monetary evidence requires an explicit meaning.")
        elif self.meaning is not None:
            raise FinancialValueError("Only monetary evidence takes an evidence meaning.")
        if self.source is None:
            if type(self.missing_reason) is not str or self.missing_reason not in _REASONS:
                raise FinancialValueError("An absent value requires a supported missing reason.")
            value = None
        else:
            if self.missing_reason is not None:
                raise FinancialValueError("A supplied value cannot have a missing reason.")
            value = _parse_number(self.source, self.kind)
        object.__setattr__(self, "value", value)

    def to_dict(self) -> dict[str, str | None]:
        """Normalized wire values are strings; original source remains separate."""
        return {
            "kind": self.kind,
            "value": format(self.value, "f") if self.value is not None else None,
            "currency": self.currency,
            "meaning": self.meaning,
            "base_currency": self.base_currency,
            "quote_currency": self.quote_currency,
            "missing_reason": self.missing_reason,
        }


def _exact_context() -> Context:
    # Three bounded operands have at most 90 coefficient digits. A cash sum has
    # at most 24. Explicit bounds/traps avoid caller/global context contamination.
    return Context(
        prec=96,
        rounding=ROUND_HALF_UP,
        Emin=-96,
        Emax=96,
        capitals=1,
        clamp=0,
        flags=[],
        traps=[
            Clamped,
            InvalidOperation,
            DivisionByZero,
            Inexact,
            Rounded,
            Subnormal,
            Overflow,
            Underflow,
            FloatOperation,
        ],
    )


def _known(value: FinancialValue, kinds: set[str]) -> Decimal:
    if type(value) is not FinancialValue or value.kind not in kinds or value.value is None:
        raise FinancialValueError("Calculation requires a known value of the correct kind.")
    return value.value


def sum_cash(values: Iterable[FinancialValue], *, currency: Currency) -> FinancialValue:
    """Sum 1..10,000 known native cash amounts; does not attest to source coverage."""
    _currency(currency)
    count = 0
    try:
        with localcontext(_exact_context()):
            total = Decimal("0")
            for count, item in enumerate(values, 1):
                if count > MAX_SUM_ITEMS:
                    raise FinancialValueError("Cash aggregation exceeds its item limit.")
                amount = _known(item, {"cash"})
                if item.currency != currency:
                    raise FinancialValueError("Cash aggregation requires one native currency.")
                total += amount
    except DecimalException:
        raise FinancialValueError("Cash aggregation could not be performed exactly.") from None
    if not count:
        raise FinancialValueError("An empty cash collection has unknown coverage.")
    return FinancialValue("cash", format(total, "f"), currency=currency)


def display_valuation(
    quantity: FinancialValue,
    price: FinancialValue,
    *,
    fx: FinancialValue | None = None,
) -> FinancialValue:
    """Round quantity × price [× directed FX] once, for display only.

    Callers must establish matching instrument, dates and source completeness.
    This primitive does not produce a booked settlement or portfolio return.
    """
    units = _known(quantity, _QUANTITY_KINDS)
    unit_price = _known(price, {"unit_price"})
    currency = price.currency
    rate = Decimal("1")
    if fx is not None:
        rate = _known(fx, {"fx_rate"})
        if fx.base_currency != currency:
            raise FinancialValueError("FX base currency must match the price currency.")
        currency = fx.quote_currency
    try:
        with localcontext(_exact_context()) as context:
            total = units * unit_price * rate
            # The only intentionally inexact operation: final minor-unit display.
            context.traps[Inexact] = False
            context.traps[Rounded] = False
            rounded = total.quantize(_MINOR_UNIT, rounding=ROUND_HALF_UP)
    except DecimalException:
        raise FinancialValueError("Display valuation exceeds its arithmetic contract.") from None
    return FinancialValue("display_amount", format(rounded, "f"), currency=currency)


@dataclass(frozen=True, slots=True)
class FinancialDate:
    """A calendar date with no invented timezone or midnight timestamp."""

    source: str = field(repr=False)
    value: date = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if (
            type(self.source) is not str
            or len(self.source) != 10
            or not _DATE.fullmatch(self.source)
        ):
            raise FinancialValueError("Expected a calendar date in YYYY-MM-DD form.")
        try:
            value = date.fromisoformat(self.source)
        except ValueError:
            raise FinancialValueError("Invalid calendar date.") from None
        object.__setattr__(self, "value", value)

    def to_dict(self) -> dict[str, str]:
        return {"value": self.value.isoformat(), "precision": "date"}


@dataclass(frozen=True, slots=True)
class FinancialInstant:
    """An explicit-offset instant normalized to UTC, preserving source precision."""

    source: str = field(repr=False)
    value: datetime = field(init=False, repr=False)
    source_offset: str = field(init=False)
    fractional_digits: int = field(init=False)

    def __post_init__(self) -> None:
        if type(self.source) is not str or not 20 <= len(self.source) <= 32:
            raise FinancialValueError("Expected a bounded timestamp with an explicit offset.")
        match = _INSTANT.fullmatch(self.source)
        if not match:
            raise FinancialValueError("Expected an ISO timestamp with seconds and an offset.")
        # Do not let a permissive ISO parser normalize 24:00 into the next day.
        if (
            int(self.source[11:13]) > 23
            or int(self.source[14:16]) > 59
            or int(self.source[17:19]) > 59
        ):
            raise FinancialValueError("Invalid timestamp clock fields.")
        offset = match["offset"]
        if offset != "Z":
            hours, minutes = int(offset[1:3]), int(offset[4:6])
            if minutes > 59 or hours > 14 or (hours == 14 and minutes != 0) or offset == "-00:00":
                raise FinancialValueError("Unsupported or unknown timestamp offset.")
        try:
            value = datetime.fromisoformat(self.source).astimezone(UTC)
        except ValueError, OverflowError:
            raise FinancialValueError("Invalid timestamp or UTC range.") from None
        object.__setattr__(self, "value", value)
        object.__setattr__(self, "source_offset", offset)
        object.__setattr__(self, "fractional_digits", len(match["fraction"] or ""))

    def to_dict(self) -> dict[str, str | int]:
        # isoformat retains four-digit years, including on platforms whose
        # strftime('%Y') does not. Preserve the supplied fractional precision.
        whole, fraction = self.value.isoformat(timespec="microseconds").split(".")
        suffix = "." + fraction[: self.fractional_digits] if self.fractional_digits else ""
        return {
            "value": whole + suffix + "Z",
            "precision": "instant",
            "source_offset": self.source_offset,
            "fractional_digits": self.fractional_digits,
        }
