# Public NAV report contracts

Step 5A implements a pure parser and explicit target matcher for the current AMFI complete NAV text layout. It is the first source contract in the [investment flow](investment-flow-plan.md). It adds no downloader, schedule, price persistence, automatic instrument creation or portfolio valuation endpoint.

[Step 5F.1](amfi-nav-reader.md) separately implements an internal fixed-destination reader around this unchanged parser. The reader is not connected to application routes, configuration or jobs; source-use entitlement, retained prices and valuation remain separate boundaries.

## Input and exact evidence

The [official download page](https://www.amfiindia.com/net-asset-value/nav-download) links the [current report](https://portal.amfiindia.com/spages/NAVAll.txt). Its observed eight-column header includes scheme code, payout/growth ISIN, reinvestment ISIN, scheme name, plan, option, NAV and date. The old six-column layout is rejected. This is a checked layout, not a provider compatibility guarantee for future changes.

`parse_report(bytes)` accepts at most 4 MiB, 50,000 lines, 25,000 data rows and 2,048 characters per line. Fields are bounded to 256 characters, with narrower financial and identifier contracts. Input must be strict UTF-8, with optional leading BOM, LF or CRLF line endings and the exact header. Controls, HTML error bodies, wrong column counts, invalid decimals/dates, excessive size and empty reports fail with a fixed error containing no input text. Category and AMC headings supply no financial or instrument identity.

Each row preserves its one-based file line, one-based data occurrence, exact source fields, original date string and parsed calendar date. The report digest covers the original bytes, including line endings. Numeric strings never pass through floats or ambient Decimal rounding. Missing NAV (`''` or `'-'`) remains explicit absence; reported zero and negative values remain inspectable and unusable.

Supplied ISIN fields are checked with the existing checksum validator. Blank/dash identifiers remain absent. Other invalid identifier text is preserved with `identity_supported=False`; the row cannot supply a usable price. It is never trimmed, corrected or interpreted as a security code. Invalid identity in one unrelated row does not erase valid report evidence.

## Explicit matching and freshness

`NavTarget` requires an exact scheme code, valid ISIN, direct/regular plan and growth/payout/reinvestment option. It does not accept names as a mapping key. `match_nav` requires the report, that target, an explicit market calendar date and a maximum age in whole days (0–365). There is no implicit clock, default freshness window or weekend inference.

Matching considers rows sharing the scheme code or ISIN. No candidate returns `missing`; multiple candidates return `ambiguous`, even when their values agree. One candidate must agree on scheme code and the correct ISIN column. Payout/growth uses the first ISIN column, reinvestment the second. Conflicting identities, plans/options, duplicate ISIN roles or contradictory distribution labels withhold a usable result.

The initial label vocabulary is deliberately small: `Direct Plan`/`Regular Plan`; `Growth`/`Growth Option`; and `IDCW`, `IDCW Option`, `IDCW Payout`, `IDCW Payout Option`, `IDCW Reinvestment`, `IDCW Reinvestment Option`, compared case-insensitively. Other labels, including incomplete fields and unverified distribution frequencies, return `unsupported_variant`. Add vocabulary only with explicit semantics and tests; never derive it from a fund name.

Results distinguish usable, missing, ambiguous, identity conflict, unsupported identity/variant, missing price, nonpositive price, future price and stale price. `evidence` retains a unique inspected row when available; `usable` returns a row only for the usable outcome. Freshness compares its original observation date with the supplied market date. Download time cannot make old evidence current.

## Verification and limits

Fabricated tests cover source precision/order, BOM/CRLF, numeric AMC headings, direct/regular and both ISIN roles, missing/zero/negative values, duplicates/conflicts, invalid identities, future/stale dates, malformed text, strict inputs and every resource boundary. They contain no customer statements or real portfolio data.

A separate bounded read of the public report on 24 October 2026 parsed 14,412 rows from 1,525,087 bytes. The temporary source copy was removed after research; only counts and its digest remain locally. It is not a committed fixture, CI dependency, portfolio seed or source-account connection. The report contains unsupported identity/variant evidence; successful parsing does not mean every row is eligible for valuation. Live reports can change. AMFI's [terms](https://www.amfiindia.com/terms-of-use) restrict significant electronic storage and broader reuse; acquisition/history permissions remain unresolved and application acquisition remains inactive.

Original occurrences above 1,000 remain intact. [Step 5F.2](amfi-market-provenance.md) extends the internal market contract, database constraint and encrypted recovery for explicit version 2 AMFI NAV positions through 25,000. Owner and archive quotas remain unchanged. A separate adapter must preserve report-to-target provenance before connecting parser output to owned records; renumbering selected rows would lose source meaning. The parser itself performs no network or database operation, and its output cannot change financial records. Any future worker response or HTTP payload must cross its own strict validation and ownership boundary.
