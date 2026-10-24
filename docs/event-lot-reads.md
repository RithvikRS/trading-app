# Event and lot history reads

Step 4G.2a exposes persisted event and lot evidence through the [protected financial query boundary](financial-reads.md). It retains native exact values, source coverage, independent dates, cancellation and every correction revision. It adds no aggregate balance, inferred remaining quantity, calculated tax basis, financial mutation or provider connection. Snapshot and market selection reads follow in 4G.2b.

## Requests and pagination

Use read-only `POST` requests with bounded JSON bodies, the active MFA session cookie and its bound CSRF token at the configured API origin. Query strings remain forbidden. The existing host/origin, session/revocation, ownership/RLS, read-only transaction, no-store and generic failure protections apply to every route.

| Route under `/api/v1/finance` | Required field | Optional fields | Result |
| --- | --- | --- | --- |
| `/events/query` | `account_id` | `limit`, `after` | Latest revision of each event in the account, including cancelled roots |
| `/events/history` | `id` | `limit`, `before` | All retained revisions of one event, newest first |
| `/lots/query` | `position_id` | `limit`, `after` | Lot identities for an account position |
| `/lots/observations/query` | `lot_id` | `limit`, `after` | Latest revision of each observation associated with one lot, including cancellations |
| `/lots/observations/history` | `id` | `limit`, `before` | All retained revisions of one lot observation, newest first |

Required IDs and `after` use canonical lowercase nonzero UUID strings. `limit` is a strict integer from 1 through 100, default 25. `before` is a positive integer revision through 9,007,199,254,740,991 or null; booleans, floats and numeric strings are rejected. Unknown request fields are rejected. Required foreign and missing parents have the same generic `404`; an owned parent without records returns an empty page.

Current pages return `items` and `next_after`, with roots ordered by UUID ascending. History pages return `items` and `next_before`, with revisions ordered descending. A non-null continuation equals the final returned ID or revision only when another record exists. SQL fetches at most `limit + 1` records; each component projection is independently bounded. Each request is consistent under the owner lock, while pages across requests remain live reads. Restart a listing to discover new roots or revisions inserted before an earlier cursor.

## Evidence semantics

Events include `id`, `revision`, `is_current`, `status`, `correction_reason`, `kind`, `posting_state`, `account_id`, nullable `position_id`/`instrument_id`, and separate `trade_date`, `settlement_date`, `booking_date` and `value_date`. Dates stay calendar dates without an invented timezone. Posted and pending evidence remain distinct. `is_current` means this root has no later revision; it does not mean active, posted, fresh or complete. A cancellation may be the current revision and has no components. Older revisions retain their original values and status.

Each event or lot observation includes opaque `source_row_id`, `source_review_revision`, `source_id`, `observation_id`, `batch_id`, original `coverage`, paired `period_start`/`period_end`, `cash_date_basis`, and current `account_state`. Source coverage describes the original observation, not proof that all account history is complete or that an import has a reconciled completion receipt. Provenance remains historical even if source mappings or later review state change. Receipt inspection is a separate increment.

Every component explicitly carries `role`, nullable decimal-string `source`, nullable native `currency`, and nullable `missing_reason`. Decimal strings retain their supplied precision and trailing zeros; JSON floating-point numbers never represent money or units. A missing fee or reported tax basis stays null with its reason, while supplied zero stays a decimal string. Quantities have no currency; monetary roles retain their own supplied currency. No display-currency conversion is performed.

Lot identities carry only `id`, `position_id`, `account_id`, `instrument_id` and `account_state`. They contain no quantity. Lot observations add `lot_id`, scope (`lot_acquisition` or `lot_remaining`), separate `as_of_date`, `acquisition_date` and `booking_date`, and exact components. Acquisition cost, discount evidence and reported tax basis stay different roles. Multiple observations are not summed or automatically selected. A reported remaining quantity does not reconstruct purchases, sales or tax lots.

## Security, recovery and verification

Fixed SQL field lists and strict frozen response schemas omit owner IDs, encrypted private references, provider transaction identifiers, hashes, fingerprints, keys and source descriptions. Queries require no private-identifier decryption. Responses are validated and encoded within the existing 256 KiB ceiling; invalid or oversized results fail without a partial success. Application-data failures return the fixed `financial_data_unavailable` envelope without clearing a valid session. Logs omit financial values, identifiers and SQL diagnostics.

Synthetic tests cover exact values, null versus zero, independent dates, posted/pending state, correction/cancellation/reinstatement history, all five pagination routes, two-owner denial, archived records, schema/CSRF/session checks, bounded SQL projections and safe database failure. The separate-cluster encrypted recovery drill compares restored event and lot history pages after fresh sign-in and continues to deny pre-restore sessions.

There is no migration, privilege, dependency or recovery-format change. The schema remains `0017_reconciled_completion`, recovery format 13, with 40 application tables and 38 durable tables. Fixtures stay disposable and fabricated. The protected frontend remains empty until Stage 5; hosted Supabase, real statement formats and production workload capacity are not verified by these tests.
