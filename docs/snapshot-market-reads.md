# Snapshot and market evidence reads

Step 4G.2b adds dated position/cash snapshots, instrument listings, quote/NAV and directed FX observations, and explicit source-selection history to the [protected financial API](financial-reads.md). The API separates retained evidence, saved selection intent and a selection that is usable now. It does not calculate portfolio totals, convert currencies, infer complete holdings or choose newer evidence automatically.

## Read contracts

All routes use read-only `POST` requests under `/api/v1/finance`, with bounded JSON bodies, the active MFA session and bound CSRF token at the configured API origin. The existing exact host/origin, no-query-string, no-store, session/revocation and owner/RLS controls apply.

| Route suffix | Required body | Optional fields | Result |
| --- | --- | --- | --- |
| `/snapshots/query` | `account_id` | `limit`, `after` | Current snapshot roots, including cancellations |
| `/snapshots/history` | `id` | `limit`, `before` | Snapshot revisions, newest first |
| `/snapshots/selections/query` | `account_id` | `limit`, `after` | Current saved choices for the account's native cash/position scopes |
| `/snapshots/selections/history` | `id` | `limit`, `before` | Saved choice revisions, including clear actions |
| `/snapshots/selections/resolve` | `id` | None | Current choice, current validity state and usable snapshot when available |
| `/listings/query` | `instrument_id` | `limit`, `after` | Instrument's exchange listings and native quote currencies |
| `/markets/observations/query` | `kind`; `instrument_id` for `quote`/`nav` | `limit`, `after` | Retained market observations for the explicit scope, including superseded reports |
| `/markets/observations/inspect` | `id` | None | One retained market observation |
| `/markets/selections/query` | `kind`; `instrument_id` for `quote`/`nav` | `limit`, `after` | Current saved choices for those native market targets |
| `/markets/selections/history` | `id` | `limit`, `before` | Market choice revisions, newest first |
| `/markets/selections/resolve` | `id` | None | Current choice, current validity state and usable observation when available |

`kind` is `quote`, `nav` or `fx`. FX queries forbid an instrument and return the owner's explicitly directed pairs; price queries require an owned instrument. A quote query may return several exchange listings, bases or providers; the fields keep those meanings separate. A NAV query stays within one direct/regular and distribution variant. Listing responses carry `id`, `instrument_id`, `venue`, `symbol`, `series` and `quote_currency`; symbol equality never merges listings.

Identifiers, limits and cursor behavior follow [event/lot pagination](event-lot-reads.md#requests-and-pagination): canonical nonzero UUID strings, strict integer page sizes 1–100 (default 25), ascending root IDs and descending positive revision cursors. Pages return `items` with `next_after` or `next_before` only when another record exists. SQL fetches at most `limit + 1` records, with bounded component projections. History is saved intent, not a live validity assessment of each historical choice. Required foreign/missing parents have uniform generic `404` responses; owned empty scopes return empty pages. Separate requests are live pages rather than a frozen export.

## Snapshot evidence and choices

Snapshots retain the [common source provenance and exact components](event-lot-reads.md#evidence-semantics), `kind`, nullable `position_id`/`instrument_id`, native `currency`, correction reason, separate `as_of_date`, original `as_of_instant`, `booking_date`, `snapshot_scope` and `reconciliation_boundary`. Date-only evidence stays date-only. An explicit timestamp keeps its source offset and fractional precision; the API never invents midnight or silently changes the source-local calendar date. Original period coverage and before/after-period boundaries remain distinct claims.

`is_current` means no later revision exists for that root. It does not mean active, complete, chosen or recent. Current pages include cancelled roots with empty components. Archived accounts remain inspectable with explicit `account_state`. Quantities, missing unit prices and native cash retain their supplied decimal strings or explicit missing reason; neither several snapshots nor several accounts imply an additive total.

Saved choices carry `id`, `revision`, `is_current`, `account_id`, nullable `position_id`/`currency`, pinned `snapshot_id`/`snapshot_revision`, and `reason`. Resolving a choice returns `selection`, `state` and `snapshot`. State is `selected`, `unselected`, `stale`, `cancelled`, `archived` or `conflicting`; only `selected` carries a snapshot. Resolution reuses the existing [selection validity rules](snapshot-evidence.md), including current revision, review/source/mapping context, normalized-batch integrity and competing evidence. A correction can leave the saved choice pointing at an older revision; its intent remains inspectable while its usable payload is withheld.

## Market observations and choices

Market observations carry `id`, optional correction `previous_id`, `is_current`, exact target fields (`kind`, `instrument_id`, `listing_id`, `currency`, `base_currency`, `quote_currency`, `basis`), quote `adjustment`, source `namespace`, `observed_on`, original `observed_at`, decimal-string `source`, `missing_reason` and `usable`. Market corrections create a new observation ID; they do not invent an event-style revision number. Retained predecessor links and inspection keep original reports accessible.

Zero, negative or missing reported prices/rates remain inspectable but are unusable. Split-adjusted or unknown-adjustment quotes are also unusable for ordinary valuation. A superseded observation may still have a valid positive number: `usable` describes its value/adjustment semantics, while `is_current` describes correction history. Neither flag establishes recency. FX source values mean quote-currency units per one base-currency unit; the API does not invert a pair or combine values across directions.

Market choices carry the exact target fields plus `id`, `revision`, `is_current`, nullable `observation_id` and `reason`. Resolution returns `selection`, `state` and `observation`, using the existing [market selection rules](market-evidence.md). State is `selected`, `unselected`, `stale` or `unusable`; only `selected` includes an observation. No freshness-age policy, provider ranking, automatic replacement, cross-date valuation or investment-return calculation is introduced.

## Security and verification

Public projections and strict response schemas omit owner IDs, encrypted identifiers, provider transaction references, hashes, digests and custody metadata. Selection validity checks may read normalized digests internally to verify a staged batch, without exposing them. They require no private-identifier decryption. A resolve request evaluates one selection and the existing bounded batch, rather than resolving every record in a listing. All reads share the owner lock and read-only transaction boundary, final session validity check, 256 KiB response ceiling, fixed error envelopes and value-free logs. Unavailable application data does not clear a valid session.

Synthetic tests cover source timestamp precision, native zero versus missing evidence, stale/cancelled/conflicting/archived/cleared choices, correction history, exact quotes and bidirectional FX, unusable reports, separate fund variants/listings, pagination and all required-parent ownership/browser boundaries. The separate-cluster recovery drill compares snapshot and market API responses under fresh sign-in alongside stored-data and old-session denial checks.

No migration, privilege, dependency or recovery-format change is required: the schema remains `0017_reconciled_completion`, recovery format 13, with 40 application tables and 38 durable tables. Fixtures are fabricated and disposable. Import/review/receipt inspection and persistence acceptance follow in 4G.3; the protected frontend remains empty until Stage 5. Hosted providers, source formats and production workload capacity remain separate verification work.
