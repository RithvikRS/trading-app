# Quote, NAV and FX evidence

[Step 4E.2](financial-data-plan.md) adds internal [market services](../backend/trading_db/markets.py) and [typed contracts](../backend/trading_db/market_contracts.py). Migration [0012_market_evidence](../backend/migrations/versions/0012_market_evidence.py) creates `market_observations` and `market_selections`. The services retain exact source evidence and explicit choices. Provider downloads, schedules, portfolio valuation, HTTP routes and connected screens remain separate work.

## Exact targets

| Kind | Required identity | Basis |
| --- | --- | --- |
| Quote | Owned equity/ETF instrument, its exact listing, and the listing's INR or USD currency | `close` or `last`, with explicit `unadjusted`, `split_adjusted` or `unknown` adjustment |
| NAV | Owned mutual-fund variant, including its existing scheme, direct/regular plan and distribution option; INR and no listing | `nav` |
| FX | Explicit distinct INR/USD base and quote currencies; no instrument or listing | `reference` or `spot` |

Ticker/name similarity never selects a target. A direct-plan NAV cannot supply a regular-plan observation. A USD→INR rate means INR per USD; the inverse is a separate observation. The service neither inverts rates nor combines currencies. Market-wide evidence is independent of source accounts and does not require a fabricated bank account.

Each observation preserves its source-local calendar date and optional explicit-offset timestamp. Date-only records remain date-only. Timestamp offsets and fractional precision survive exactly, while validation rejects ambiguous timestamps and mismatched source-local dates. These dates describe supplied market evidence; database insertion time does not make a price fresh. Position dates, price dates and FX dates stay independent.

## Values and provenance

`ReportedMarketValue` preserves the original decimal string and exact numeric value with the established 18-integer/12-fractional-digit bound. Missing evidence requires a supported missing reason. Reported zero and negative values remain evidence, but cannot be used as a price/rate. The existing `FinancialValue` contract still requires positive usable prices and rates. Quote evidence with unknown or split-adjusted basis is also unavailable for current-unit selection; this increment does not implement split-aware historical valuation.

Source identity includes owner, namespace, SHA-256 digest, occurrence, normalizer and normalizer version. Namespaces are bounded: manual evidence, AMFI NAV report, exchange quote report or FX rate report, constrained to their respective kinds. The digest identifies supplied evidence; it does not authenticate a provider or demonstrate that a file was fetched. Occurrences distinguish legitimate repeated rows. The contract version is currently 1 and independent of import normalization contracts 1–4.

An exact source-identity replay returns the original observation. Changed content under that identity fails, including changed original formatting, dates or target. Another namespace, occurrence or normalization version has its own evidence identity. All material fields are typed columns; unrestricted payloads do not replace database constraints.

## Corrections and explicit selection

Observations are immutable. A supplied correction can reference one existing, current predecessor with the same exact target and basis. Only one successor is allowed, and cycles are rejected even during recovery. A correction preserves earlier evidence and makes a selection of its predecessor stale. It never silently chooses the successor.

Selections form an append-only revision history per exact target and basis. Initial selection uses `reviewed`; subsequent selections use `replacement` or `correction`. A correction choice must select the immediate correction of the previously selected observation. Clearing a selection retains its history and yields an unavailable current value. Expected revisions protect writes; exact historical retries return the original selection, while changed retries conflict.

Only positive, usable, unsuperseded observations can be newly selected. Resolution takes the same owner lock as writers so concurrent corrections cannot produce mixed reads. States are `selected`, `unselected`, `stale`, or defensively `unusable`; only `selected` exposes a usable observation. Here `stale` means superseded evidence, not an age threshold. A selected observation may still be old: future valuation must evaluate dates, calendars, basis and coverage before displaying totals.

Different providers may report different market prices. The service retains those observations and the explicit choice; it does not sum them or apply the snapshot quantity-conflict rule to prices. No automatic latest-price selection, source ranking, fallback, inferred price, or zero-valued portfolio result is introduced.

## Ownership and recovery

Both tables use forced active-owner row policies, composite owner foreign keys, immutable runtime records, narrow insert grants, and database-assigned audit timestamps. Authentication-role access is denied. Direct SQL validates value/source equality, target identity, dates, source kinds, correction history and selection usability. Runtime writes serialize with the existing owner lock. Each table is bounded to 1,000 records per owner; reads default to 25 records and allow at most 100 with stable opaque-ID or revision pagination. Error messages and object representations omit financial values.

Recovery format **8** covers **34 application tables**: 32 durable and the two intentionally omitted session/admission tables. The separate-cluster encrypted drill restores source strings, timestamps, corrections, missing/unusable observations, selected rates, cleared NAV selections and earlier selection revisions for two owners. It compares all durable rows, constraints, grants and policies, then verifies effective reads. Private identifier keys are recovered separately and prior sessions remain revoked.

Migration creates no owner or financial data. The disposable-only downgrade refuses populated market tables; transactional failure restores the preceding schema and forced policies. Older recovery objects require their matching release/schema before a tested forward migration. General-volume backups, hosted compatibility and provider authenticity remain separate operational work.

## Verification

[Contract tests](../backend/tests/test_markets.py) cover exact decimals, missing/nonpositive evidence, currency direction, timestamp precision and unsupported identities. [PostgreSQL tests](../backend/database_tests/test_markets.py) exercise replay conflicts, correction/selection history, concurrency, separate fund variants, foreign IDs, direct-SQL tampering, grants, forced policies, bounded reads and migration safety. The [encrypted recovery test](../backend/database_tests/test_recovery.py) includes all market tables alongside existing financial history. Run the shared [verification commands](verification.md); only fabricated evidence is used.
