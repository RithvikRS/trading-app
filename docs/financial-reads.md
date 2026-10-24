# Protected financial reads

Step 4G.1 exposes owned account, source-mapping, instrument and position identities through the authenticated Python API. These records carry no inferred balances, holdings quantities or valuation totals. The protected frontend remains empty; connected views follow with their complete data flow in Stage 5.

[Step 4G.2a](event-lot-reads.md) adds dated event/lot evidence and retained history. [Step 4G.2b](snapshot-market-reads.md) adds dated snapshot/market evidence, listings and selection history/resolution. Step 4G.3 adds import/review/receipt inspection and the remaining persistence acceptance checks. No financial mutation, upload, download from a provider, export or administrative route is introduced by these read increments.

## Request contract

All identity queries use `POST` with `application/json` at the existing API origin. These operations read financial records. The JSON body keeps account filters and pagination references out of URLs, proxy access targets and browser history. Query strings remain forbidden across authentication, preferences and financial routes.

| Route | Required body fields | Optional body fields | Result |
| --- | --- | --- | --- |
| `/api/v1/finance/accounts/query` | None | `limit`, `after` | Canonical account identities, native currency membership and lifecycle state |
| `/api/v1/finance/sources/query` | None | `limit`, `after` | Source namespace and latest explicit account-mapping revision |
| `/api/v1/finance/instruments/query` | None | `limit`, `after` | Instrument identity, ISIN, asset class and explicit mutual fund variant |
| `/api/v1/finance/positions/query` | `account_id` | `limit`, `after` | Account/instrument/holding-form identities within that owned account |

`{}` is a valid account/source/instrument query. `limit` is a strict integer from 1 through 100, defaulting to 25. Booleans, numeric strings and fractional values are rejected. `after` is a canonical lowercase nonzero opaque UUID string or null. `account_id` follows the same identifier format. Unknown fields, including client-supplied ownership, amounts and free-form searches, are rejected. No arbitrary SQL sorting or projection fields are accepted.

Responses have exactly `items` and `next_after`. Records are ordered by opaque UUID ascending. `next_after` equals the last returned identity only when another row exists; otherwise it is null. SQL retrieves at most `limit + 1` records, never an unbounded list for later slicing. The source mapping projection selects only its latest revision. Each page is consistent under the existing owner transaction lock. Pages across separate requests are live reads, not a frozen export; newly added records before the cursor require a fresh listing.

An empty owned account produces an empty positions page. An unknown or foreign required account produces the same generic `404`. A cursor is only an ordering value and never confirms whether the corresponding record exists. Archived accounts remain readable with explicit state, preserving identity and history.

## Explicit response fields

- Accounts: `id`, `kind`, `institution`, `market`, safe `label`, `currencies`, `revision`, and `state` (`active` or `archived`). Currency membership does not imply a reported balance.
- Sources: `id`, `namespace`, `mapping_revision`, `account_id`, and `state` (`mapped`, `unmapped`, or `archived`). A never-mapped source has a null revision; an explicitly unlinked source retains the latest revision with a null account. An archived mapping target stays visible as archived.
- Instruments: `id`, `name`, `isin`, `asset_class`, `fund_scheme_id`, `fund_plan`, `fund_option`, and `fund_currency`. Fund variant fields are mandatory for mutual funds and null for other asset classes. Direct and regular funds remain separate identities.
- Positions: `id`, `account_id`, `instrument_id`, `holding_form`, and `account_state`. Several positions may describe distinct holding forms or accounts; these identities are not quantities and must not be summed as assets.

Database projections and frozen response schemas independently allowlist these fields. They do not serialize internal database objects or use unrestricted table projections. No owner ID, encrypted private reference, fingerprint, key metadata, provider token, account number or folio reference is returned. Identity reads require no financial-identifier decryption key and do not query private custody columns.

Responses are fully validated and encoded inside the bounded owner transaction, with a 256 KiB response ceiling. Oversized or invalid stored projections fail as unavailable; they are not truncated. These identity responses contain no monetary values. The [event/lot routes](event-lot-reads.md) retain exact decimal strings, native currency, separate dates, coverage and missing reasons.

## Authentication and failure boundary

The complete `/api/v1/finance` route family is inside the existing [browser boundary](browser-sessions.md), including unknown child paths. Reads require a verified active MFA session, exact configured host/origin and a valid CSRF token bound to the session. Authorization headers, cross-site or same-site fetches, ambiguous critical headers/cookies, and query strings are rejected. Unsupported methods expose no financial data or mutations.

Request bodies retain the 4 KiB limit and five-second receive deadline. Compressed and form bodies are rejected. Financial JSON additionally requires valid UTF-8, unique object keys, finite numbers and at most 16 levels of nesting. Malformed bodies return a fixed error without echoing inputs.

The session determines the owner independently of every request field. The restricted runtime role sets transaction-local ownership and forced RLS remains active. Financial queries also use a PostgreSQL read-only transaction, so an accidental write fails at the database boundary. The setting is transaction-local and does not prevent later authorized writes through the same pool. A short session guard orders admitted reads against revocation; provider refresh occurs before the financial transaction. Session/owner validity is checked again after constructing the response. Expiry or identity disabling during SQL prevents data release. Background reads do not extend idle lifetime.

Database/query failures return `503` with `financial_data_unavailable` and a generated request ID. They do not clear an otherwise valid session. Authentication failures retain their existing response and cookie behavior. Unknown/foreign parent IDs return `404`; invalid query schemas return `422`; boundary errors retain fixed `400`, `403`, `413` or `415` envelopes. Every response uses the existing no-store and security headers. Logs retain fixed event/status/request IDs, without route filters, bodies, row values, SQL diagnostics or private identifiers.

## Verification and limits

Synthetic contract/browser tests cover canonical JSON UUIDs, strict pagination, preserved concrete response fields, ambiguous/nonfinite/deep JSON, all new route families, streamed bodies and the receive deadline. Real PostgreSQL/HTTP tests cover two-owner isolation, archived/unmapped states, distinct fund/position identities, complete keyset pages, missing and foreign parents, active MFA, recovery and revoked sessions, before/after-query validity checks, concurrent logout, application restart, connection cleanup and private-field omission. Query failure tests verify that a valid session can immediately read again.

The existing separate-cluster encrypted recovery drill checks restored identity pages through a fresh authenticated session and denies pre-restore sessions. No migration, schema, privilege grant, recovery-format or dependency change is required for this read increment: the database stays at `0017_reconciled_completion`, recovery format 13, with 40 application tables and 38 durable tables.

Run the [shared verification groups](verification.md) and record their actual results in the increment's PR. Local synthetic reads do not verify hosted Supabase configuration, real source formats, Oracle capacity or financial-volume backup performance. No Supabase project or live source account is used.

[Step 4G.3a](import-review-reads.md) adds source observations, normalized batch/row inspection and immutable review history, retaining exact evidence and current mapping validity. Completion receipt/comparison reads follow in 4G.3b.
