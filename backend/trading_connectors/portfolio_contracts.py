"""Private, exact reader evidence; these are application contracts, not provider schemas."""

import json
import re
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from trading_api.finance import (
    Currency,
    FinancialInstant,
    FinancialValue,
    FinancialValueError,
    ReportedMarketValue,
)

MAX_RESPONSE_BYTES = 262_144
MAX_ROWS = 2_000


class PortfolioReadError(RuntimeError):
    def __init__(
        self,
        reason: Literal[
            "compatibility", "unavailable", "authorization", "rate_limited", "capacity", "limits"
        ] = "unavailable",
    ) -> None:
        self.reason = reason
        super().__init__("Portfolio read did not complete.")


@dataclass(frozen=True, slots=True)
class JsonNumber:
    """Keep the original JSON number token, including zeros; never construct a float."""

    source: str = field(repr=False)


def exact_document(raw: bytes) -> dict[str, Any]:
    """Bound syntax before decoding; reject duplicate keys, non-finite values and depth bombs."""

    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        if len(pairs) > 128 or len(dict(pairs)) != len(pairs):
            raise ValueError()
        return dict(pairs)

    def number(source: str) -> JsonNumber:
        if len(source) > 64:
            raise ValueError()
        return JsonNumber(source)

    def reject(_: str) -> None:
        raise ValueError()

    try:
        if type(raw) is not bytes or not 1 <= len(raw) <= MAX_RESPONSE_BYTES:
            raise ValueError()
        depth, quoted, escaped = 0, False, False
        for byte in raw:
            if quoted:
                if escaped:
                    escaped = False
                elif byte == 92:
                    escaped = True
                elif byte == 34:
                    quoted = False
            elif byte == 34:
                quoted = True
            elif byte in (91, 123):
                depth += 1
                if depth > 16:
                    raise ValueError()
            elif byte in (93, 125):
                depth -= 1
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=unique,
            parse_int=number,
            parse_float=number,
            parse_constant=reject,
        )
        if type(value) is not dict:
            raise ValueError()
        pending: list[Any] = [value]
        count = 0
        while pending:
            node = pending.pop()
            count += 1
            if count > 20_000:
                raise ValueError()
            if type(node) is dict:
                pending.extend(node.keys())
                pending.extend(node.values())
            elif type(node) is list:
                if len(node) > MAX_ROWS:
                    raise ValueError()
                pending.extend(node)
            elif type(node) is str:
                # Reject escaped controls/surrogates as well as invalid UTF-8 on the wire.
                if len(node) > 65_536 or any(
                    ord(c) < 32 and c not in "\n\r\t" or 0xD800 <= ord(c) <= 0xDFFF for c in node
                ):
                    raise ValueError()
        return value
    except ValueError, UnicodeError, RecursionError:
        raise PortfolioReadError("compatibility") from None


def source_decimal(value: object) -> str:
    if type(value) is JsonNumber:
        return value.source
    if type(value) is str:
        return value
    raise PortfolioReadError("compatibility")


def identifier(value: object) -> str:
    # A private, opaque source key. Never derive identities from names or fetch these as URLs.
    if type(value) is not str or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}", value):
        raise PortfolioReadError("compatibility")
    return value


def cursor_value(value: object) -> str | None:
    if value is None:
        return None
    if type(value) is not str or not re.fullmatch(r"[\x21-\x7e]{1,512}", value):
        raise PortfolioReadError("compatibility")
    return value


def instant(value: object) -> FinancialInstant | None:
    if value is None:
        return None
    if type(value) is not str:
        raise PortfolioReadError("compatibility")
    try:
        return FinancialInstant(value)
    except FinancialValueError:
        raise PortfolioReadError("compatibility") from None


@dataclass(frozen=True, slots=True, repr=False)
class HoldingEvidence:
    account: str
    instrument: str
    asset: Literal["indian_equity", "us_equity", "mutual_fund"]
    currency: Currency
    quantity: FinancialValue
    price: ReportedMarketValue
    acquisition_cost: FinancialValue
    folio: str | None = None
    plan: Literal["direct", "regular"] | None = None
    option: Literal["growth", "distribution"] | None = None
    observed_at: FinancialInstant | None = None
    priced_at: FinancialInstant | None = None

    def __repr__(self) -> str:
        return "HoldingEvidence(<private>)"

    def __post_init__(self) -> None:
        identifier(self.account)
        identifier(self.instrument)
        if self.asset not in {"indian_equity", "us_equity", "mutual_fund"}:
            raise PortfolioReadError("compatibility")
        if self.currency != ("USD" if self.asset == "us_equity" else "INR"):
            raise PortfolioReadError("compatibility")
        if self.asset == "mutual_fund":
            identifier(self.folio)
            if self.plan not in {"direct", "regular"} or self.option not in {
                "growth",
                "distribution",
            }:
                raise PortfolioReadError("compatibility")
        elif any(value is not None for value in (self.folio, self.plan, self.option)):
            raise PortfolioReadError("compatibility")
        if (
            type(self.quantity) is not FinancialValue
            or self.quantity.kind != "position_quantity"
            or self.quantity.value is None
            or type(self.price) is not ReportedMarketValue
            or self.price.kind != "unit_price"
            or self.price.currency != self.currency
            or type(self.acquisition_cost) is not FinancialValue
            or self.acquisition_cost.kind != "monetary_evidence"
            or self.acquisition_cost.meaning != "acquisition_cost"
            or self.acquisition_cost.currency != self.currency
            or any(
                value is not None and type(value) is not FinancialInstant
                for value in (self.observed_at, self.priced_at)
            )
        ):
            raise PortfolioReadError("compatibility")

    @property
    def key(self) -> tuple[str, str, str | None, str | None, str | None]:
        return self.account, self.instrument, self.folio, self.plan, self.option


@dataclass(frozen=True, slots=True, repr=False)
class HoldingsPage:
    """A reviewed adapter must preserve every row or fail the entire page."""

    account: str
    asset: Literal["indian_equity", "us_equity", "mutual_fund"]
    holdings: tuple[HoldingEvidence, ...]
    next_cursor: str | None
    complete: bool  # Explicit provider coverage claim, not inferred from an empty cursor.
    observed_at: FinancialInstant | None

    def __repr__(self) -> str:
        return "HoldingsPage(<private>)"

    def __post_init__(self) -> None:
        identifier(self.account)
        cursor_value(self.next_cursor)
        if (
            self.asset not in {"indian_equity", "us_equity", "mutual_fund"}
            or type(self.complete) is not bool
            or self.complete
            and self.next_cursor is not None
            or type(self.holdings) is not tuple
            or len(self.holdings) > MAX_ROWS
            or self.observed_at is not None
            and type(self.observed_at) is not FinancialInstant
        ):
            raise PortfolioReadError("compatibility")
        for row in self.holdings:
            if type(row) is not HoldingEvidence or (row.account, row.asset) != (
                self.account,
                self.asset,
            ):
                raise PortfolioReadError("compatibility")
        if len({row.key for row in self.holdings}) != len(self.holdings):
            raise PortfolioReadError("compatibility")


class HoldingsContract(Protocol):
    """Trusted, code-reviewed adapter only; never construct this from remote tool metadata.

    No live adapter is shipped until the provider's machine contract is verified.
    Schemas are pinned local JSON bytes, not fetched references or executable validators.
    The decoder must reject unknown fields/rows and preserve timestamps, absence and identity.
    """

    input_schema: bytes
    output_schema: bytes
    revision: str

    def arguments(self, cursor: str | None) -> dict[str, Any]: ...

    def decode(self, value: dict[str, Any]) -> HoldingsPage: ...


@dataclass(frozen=True, slots=True, repr=False)
class PortfolioRead:
    pages: tuple[HoldingsPage, ...]
    fetched_at: FinancialInstant
    coverage: Literal["source_complete", "incomplete"]
    limitation: Literal["source_incomplete", "page_limit", "row_limit"] | None
    contract_revision: str
    schema_digest: str

    def __repr__(self) -> str:
        return f"PortfolioRead(coverage={self.coverage!r}, <private>)"

    # Even complete source pagination cannot establish application account/instrument mappings.
    @property
    def import_ready(self) -> Literal[False]:
        return False
