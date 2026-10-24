"""Bounded public NAV evidence; no acquisition, persistence or inferred identities."""

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from trading_api.finance import FinancialValueError, ReportedMarketValue
from trading_db.instruments import FundOption, InstrumentUnavailable, validate_isin

HEADER = (
    "Scheme Code;ISIN Div Payout/ ISIN Growth;ISIN Div Reinvestment;"
    "Scheme Name;Plan;Option;Net Asset Value;Date"
)
MAX_BYTES = 4 * 1024 * 1024
MAX_LINES = 50_000
MAX_ROWS = 25_000
MAX_LINE_LENGTH = 2048
_MONTHS = {
    value: index
    for index, value in enumerate(
        ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), 1
    )
}
_GROWTH = {"growth", "growth option"}
_DISTRIBUTION = {
    "idcw",
    "idcw option",
    "idcw payout",
    "idcw payout option",
    "idcw reinvestment",
    "idcw reinvestment option",
}
type MatchStatus = Literal[
    "usable",
    "missing",
    "ambiguous",
    "identity_conflict",
    "unsupported_variant",
    "unsupported_identity",
    "missing_price",
    "nonpositive_price",
    "future_price",
    "stale_price",
]


class NavUnavailable(ValueError):
    def __init__(self) -> None:
        super().__init__("NAV evidence is unavailable or unsupported.")


def _identifier(value: str) -> str | None:
    if value in {"", "-"}:
        return None
    try:
        return validate_isin(value)
    except InstrumentUnavailable:
        raise NavUnavailable() from None


def _observed(value: str) -> date:
    if re.fullmatch(r"[0-9]{2}-[A-Z][a-z]{2}-[0-9]{4}", value, re.ASCII) is None:
        raise NavUnavailable()
    day, month, year = value.split("-")
    try:
        return date(int(year), _MONTHS[month], int(day))
    except KeyError, ValueError:
        raise NavUnavailable() from None


@dataclass(frozen=True, slots=True, repr=False)
class NavRow:
    line_number: int
    occurrence: int
    scheme_code: str
    payout_or_growth_isin: str
    reinvestment_isin: str
    scheme_name: str
    plan_label: str
    option_label: str
    nav_source: str
    date_source: str
    observed_on: date = field(init=False)
    identity_supported: bool = field(init=False)

    def __post_init__(self) -> None:
        if (
            type(self.line_number) is not int
            or not 2 <= self.line_number <= MAX_LINES
            or type(self.occurrence) is not int
            or not 1 <= self.occurrence <= MAX_ROWS
            or type(self.scheme_code) is not str
            or re.fullmatch(r"[1-9][0-9]{0,11}", self.scheme_code, re.ASCII) is None
        ):
            raise NavUnavailable()
        for value in (
            self.payout_or_growth_isin,
            self.reinvestment_isin,
            self.scheme_name,
            self.plan_label,
            self.option_label,
            self.nav_source,
            self.date_source,
        ):
            if (
                type(value) is not str
                or len(value) > 256
                or any(ord(character) < 32 or ord(character) == 127 for character in value)
            ):
                raise NavUnavailable()
        if not self.scheme_name.strip():
            raise NavUnavailable()
        try:
            _identifier(self.payout_or_growth_isin)
            _identifier(self.reinvestment_isin)
            supported = True
        except NavUnavailable:
            supported = False
        object.__setattr__(self, "identity_supported", supported)
        object.__setattr__(self, "observed_on", _observed(self.date_source))
        self.reported()

    def reported(self) -> ReportedMarketValue:
        missing = self.nav_source in {"", "-"}
        try:
            return ReportedMarketValue(
                "unit_price",
                None if missing else self.nav_source,
                currency="INR",
                missing_reason="not_supplied" if missing else None,
            )
        except FinancialValueError:
            raise NavUnavailable() from None


@dataclass(frozen=True, slots=True, repr=False)
class NavReport:
    digest: str
    byte_count: int
    line_count: int
    rows: tuple[NavRow, ...]

    def __post_init__(self) -> None:
        if (
            type(self.digest) is not str
            or re.fullmatch(r"[0-9a-f]{64}", self.digest, re.ASCII) is None
            or type(self.byte_count) is not int
            or not 1 <= self.byte_count <= MAX_BYTES
            or type(self.line_count) is not int
            or not 2 <= self.line_count <= MAX_LINES
            or type(self.rows) is not tuple
            or not 1 <= len(self.rows) <= MAX_ROWS
        ):
            raise NavUnavailable()
        previous = 1
        for occurrence, row in enumerate(self.rows, 1):
            if (
                not isinstance(row, NavRow)
                or row.occurrence != occurrence
                or not previous < row.line_number <= self.line_count
            ):
                raise NavUnavailable()
            previous = row.line_number


@dataclass(frozen=True, slots=True, repr=False)
class NavTarget:
    scheme_code: str
    isin: str
    plan: Literal["direct", "regular"]
    option: FundOption

    def __post_init__(self) -> None:
        if (
            type(self.scheme_code) is not str
            or re.fullmatch(r"[1-9][0-9]{0,11}", self.scheme_code, re.ASCII) is None
            or type(self.isin) is not str
            or _identifier(self.isin) is None
            or type(self.plan) is not str
            or self.plan not in {"direct", "regular"}
            or type(self.option) is not str
            or self.option not in {"growth", "idcw_payout", "idcw_reinvestment"}
        ):
            raise NavUnavailable()


@dataclass(frozen=True, slots=True, repr=False)
class NavMatch:
    status: MatchStatus
    evidence: NavRow | None

    @property
    def usable(self) -> NavRow | None:
        return self.evidence if self.status == "usable" else None


def parse_report(data: bytes) -> NavReport:
    if type(data) is not bytes or not 1 <= len(data) <= MAX_BYTES:
        raise NavUnavailable()
    try:
        text = data.decode("utf-8-sig")
    except UnicodeError:
        raise NavUnavailable() from None
    # Only LF and CRLF are accepted. Other control characters cannot form headings.
    text = text.replace("\r\n", "\n")
    if any(
        (ord(character) < 32 and character != "\n") or ord(character) == 127 for character in text
    ):
        raise NavUnavailable()
    lines = text.split("\n")
    if len(lines) > MAX_LINES or lines[0] != HEADER:
        raise NavUnavailable()
    rows: list[NavRow] = []
    for number, line in enumerate(lines[1:], 2):
        if len(line) > MAX_LINE_LENGTH:
            raise NavUnavailable()
        if not line.strip():
            continue
        if ";" not in line:
            # Category and AMC headings confer no identity or financial meaning.
            if len(line) > 256 or not (
                line[0].isalpha()
                or re.fullmatch(r"[0-9][A-Za-z0-9 &()./'-]* Mutual Fund", line, re.ASCII)
            ):
                raise NavUnavailable()
            continue
        fields = line.split(";")
        if len(fields) != 8 or len(rows) >= MAX_ROWS:
            raise NavUnavailable()
        rows.append(NavRow(number, len(rows) + 1, *fields))
    if not rows:
        raise NavUnavailable()
    return NavReport(hashlib.sha256(data).hexdigest(), len(data), len(lines), tuple(rows))


def match_nav(report: NavReport, target: NavTarget, *, as_of: date, max_age_days: int) -> NavMatch:
    if (
        type(as_of) is not date
        or type(max_age_days) is not int
        or not 0 <= max_age_days <= 365
        or not isinstance(report, NavReport)
        or not isinstance(target, NavTarget)
    ):
        raise NavUnavailable()
    candidates = [
        row
        for row in report.rows
        if row.scheme_code == target.scheme_code
        or target.isin in {row.payout_or_growth_isin, row.reinvestment_isin}
    ]
    if not candidates:
        return NavMatch("missing", None)
    if len(candidates) != 1:
        return NavMatch("ambiguous", None)
    row = candidates[0]
    if not row.identity_supported:
        return NavMatch("unsupported_identity", row)
    expected_isin = (
        row.reinvestment_isin if target.option == "idcw_reinvestment" else row.payout_or_growth_isin
    )
    if row.scheme_code != target.scheme_code or expected_isin != target.isin:
        return NavMatch("identity_conflict", row)
    if row.payout_or_growth_isin == row.reinvestment_isin:
        return NavMatch("identity_conflict", row)
    plan = {"direct plan": "direct", "regular plan": "regular"}.get(row.plan_label.casefold())
    option = row.option_label.casefold()
    if plan is None or option not in _GROWTH | _DISTRIBUTION:
        return NavMatch("unsupported_variant", row)
    if plan != target.plan or (target.option == "growth") != (option in _GROWTH):
        return NavMatch("identity_conflict", row)
    if (target.option == "idcw_reinvestment" and "payout" in option) or (
        target.option == "idcw_payout" and "reinvestment" in option
    ):
        return NavMatch("identity_conflict", row)
    if target.option == "growth" and _identifier(row.reinvestment_isin) is not None:
        return NavMatch("identity_conflict", row)
    reported = row.reported()
    if reported.value is None:
        return NavMatch("missing_price", row)
    if not reported.usable:
        return NavMatch("nonpositive_price", row)
    age = (as_of - row.observed_on).days
    if age < 0:
        return NavMatch("future_price", row)
    if age > max_age_days:
        return NavMatch("stale_price", row)
    return NavMatch("usable", row)
