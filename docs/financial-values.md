# Exact financial value contracts: Step 4A

Implemented in [trading_api.finance](../backend/trading_api/finance.py), a pure Python domain module using the standard library. It has no database, HTTP, provider, file or network access. No financial table, migration, endpoint, seed or frontend behavior is added. The [Step 4 plan](financial-data-plan.md) continues with accounts and source mappings in 4B.

## Values and serialization

`FinancialValue` is immutable and requires a kind, original `source` string (or explicit absence), and the context appropriate to its kind. It exposes a Python `Decimal` as `value`. Source text stays separate from normalized serialization, including its original negative-zero sign and trailing fractional zeros. Normalized negative zero becomes positive zero without removing fractional precision.

Only plain ASCII decimal strings are accepted: optional minus, one to eighteen integer digits without redundant leading zeros, and an optional decimal point followed by fractional digits. Maximum length is 32. Floats, integers, booleans, preconstructed Decimals, whitespace, plus signs, separators, exponent notation, Unicode digits, NaN and infinity are rejected. Validate a documented source format before constructing these normalized values; never repair an unsupported value through float conversion or truncation.

All magnitudes must be strictly below 10^18. These are project bounds, not verified provider precision guarantees.

| Kind | Fractional digits | Required context and signs |
| --- | --- | --- |
| `cash` | 0–2 | INR/USD; signed posted amount, with transaction role supplied by its containing event |
| `monetary_evidence` | 0–8 | INR/USD and `acquisition_cost`, `reported_tax_basis`, `fee` or `withholding`; signed evidence, not a cash posting |
| `quantity_movement` | 0–12 | Signed security units; containing event supplies instrument identity |
| `position_quantity`, `lot_quantity` | 0–12 | Nonnegative security units; containing position/lot supplies instrument identity |
| `unit_price` | 0–12 | INR/USD per security unit; strictly positive usable quote/NAV |
| `fx_rate` | 0–12 | Distinct INR/USD base and quote currencies; strictly positive quote units per one base unit |
| `display_amount` | 0–2 | INR/USD; signed derived display value, distinct from booked cash |

Unused context fields must be null. Currency codes are exactly `INR` or `USD`. Record-specific rules such as fee direction, lot identity, event dates, valid source coverage and price freshness remain the responsibility of later domain records/services. Zero/nonpositive reported quotes may later be retained as source evidence but cannot construct a usable `unit_price`.

An absent value requires `source=None` and one of `not_supplied`, `incomplete_history`, `unsupported` or `conflicting_evidence` as `missing_reason`. Known values cannot have a missing reason, including a known zero. Required kind/currency/meaning context is still checked for absent values. Calculations reject unknown operands.

`to_dict()` emits the fixed keys `kind`, `value`, `currency`, `meaning`, `base_currency`, `quote_currency`, and `missing_reason`. Monetary/numeric `value` is always a plain decimal string or null; it is never a JSON number. Context fields not used by that kind are null. Source text is not part of this normalized dictionary; future provenance storage must retain it separately when required. This is an internal serialization contract, not a new request endpoint or a substitute for a bounded API request schema.

```python
from trading_api.finance import FinancialValue, sum_cash

fee = FinancialValue("cash", "-12.30", currency="INR")
missing_basis = FinancialValue(
    "monetary_evidence", None, currency="USD",
    meaning="reported_tax_basis", missing_reason="incomplete_history",
)
total = sum_cash([
    FinancialValue("cash", "100.00", currency="INR"), fee,
], currency="INR")
assert total.to_dict()["value"] == "87.70"
assert missing_basis.to_dict()["value"] is None
```

## Arithmetic boundary

`sum_cash` accepts 1–10,000 known `cash` values in one specified native currency. It preserves exact amounts, rejects other kinds/mixed currencies, and checks the final magnitude. An empty collection cannot silently become zero. A bounded sum does not establish that an account's activity is complete.

`display_valuation` multiplies known security quantity by a positive unit price and, optionally, a directed FX rate. The rate's base must match the price currency; no inversion or cross-currency guess occurs. The caller must establish matching instruments, appropriate dates, source selection and completeness. The function returns `display_amount`, which `sum_cash` rejects as booked cash.

Arithmetic uses a fresh explicit 96-digit Decimal context with bounded exponents and traps, independent of the caller's global context. Three supported operands require at most 90 coefficient digits; a bounded cash sum requires at most 24. Unexpected rounding/inexact operations fail. Only the final display quantization permits rounding to cents/paise, using half away from zero. For example, 1 unit × USD 1.005 × INR 2 per USD yields INR 2.01; rounding the price/product first would incorrectly yield 2.02. Negative ties round symmetrically, and a rounded result crossing the magnitude limit is rejected.

Source settlement amounts remain authoritative; this primitive does not replace them, reconcile an account, compute returns, or attest to a tax basis. Division, FX inversion, tax-lot allocation, residual handling and a portfolio valuation engine are not implemented. [Python Decimal context behavior](https://docs.python.org/3.14/library/decimal.html).

## Dates and instants

`FinancialDate` accepts only valid Gregorian calendar strings in `YYYY-MM-DD` form (years 0001–9999). It returns a Python `date` and serializes as `{ "value": "2026-10-24", "precision": "date" }`. No midnight timestamp or timezone is inferred. Trade, settlement, booking and value date roles belong to later records.

`FinancialInstant` requires `YYYY-MM-DDTHH:MM:SS`, optional 1–6 fractional digits, and `Z` or an explicit `±HH:MM` offset. Offsets are limited by this project contract to ±14:00, with minutes 00–59; `-00:00` is rejected as unknown. Hours must be 00–23, minutes/seconds 00–59. Naive times, alternate separators, leap seconds, `24:00`, excess fractional digits and UTC conversion outside the supported year range fail rather than normalize silently.

Its Python value is timezone-aware UTC. The original source string, supplied offset and fractional-digit count remain available. Serialization includes the normalized UTC `value`, `precision="instant"`, `source_offset`, and `fractional_digits`; it retains the original number of fractional digits. For example `2026-10-24T01:02:03.120+05:30` becomes `2026-10-23T19:32:03.120Z`, with offset `+05:30` and precision 3. No IANA zone or DST rule is guessed from an offset; ambiguous source local times stay unsupported until a parser has evidence. [Python date/time types](https://docs.python.org/3.14/library/datetime.html).

## Security and evidence

All validation messages are fixed descriptions without supplied values. Default object representations omit source text and financial/date values. Explicit serialization still contains financial information and must follow normal owner authorization, response privacy and logging rules when used later. Immutable Python objects are value contracts, not an authorization boundary.

[Focused tests](../backend/tests/test_finance.py) cover exact string/JSON round trips, precision/magnitude/sign limits, null versus zero, context misuse, oversized/malformed input, bounded sums, ties, FX direction and final-only rounding, independent rational arithmetic results, hostile ambient Decimal contexts, leap dates, offset/UTC boundary cases, repeated local hours, immutability and error/repr privacy. Run them from `backend/` with `uv run --locked pytest tests/test_finance.py` using the [pinned local setup](development.md#local-python-api), or run the shared backend checks.

Step 4A did not change schema `0005_preference_revisions`. [Step 4B](accounts-source-mappings.md) subsequently adds account/source persistence and recovery at `0006_accounts_sources`. Financial numeric SQL constraints and direct-SQL rejection tests begin with the relevant schema increments. No PostgreSQL enforcement, hosted provider compatibility or financial persistence is claimed by these Python-only contracts.
