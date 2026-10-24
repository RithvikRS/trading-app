# Reviewed snapshots and connected investments

Step 6D connects saved investment evidence to the protected workspace. The Investments page lists saved positions by account, resolves their explicit snapshot choices, and shows dated native quantities, supplied prices and missing-value reasons. A source snapshot does not establish transaction history, cost basis, performance or portfolio completeness.

Live INDmoney acquisition remains disabled. The [reader engine](indmoney-reader.md) has no verified production adapter; authorization alone does not create accounts, instruments, normalized batches or holdings. This feature operates on evidence already saved by the owned staging services. No synthetic records are inserted into the normal application. Existing account and instrument identities are prerequisites; source mappings and explicit holding-form positions can be managed during review.

## Review flow

1. Open Investments, choose a saved account, or open **Review snapshots**. The queue contains current normalized batches with snapshot coverage, including completed receipts.
2. Inspect every source occurrence, its exact supplied values, observation date/instant and effective review status. Map the source to an existing owned account and each provider identifier to an exact instrument/listing. Mutual-fund plan and distribution option remain separate identities. Changing a mapping makes older include decisions require review again.
3. Include, exclude or reopen rows using their current decision revision. Included position snapshots require an explicit position; creation requires a selected holding form. Names never cause automatic matching. Completed batches cannot change row decisions through this workflow.
4. Choose **record separate source evidence** or **correct existing snapshot**. Inspect existing evidence before selecting a correction target. Source choice is an independent, unchecked-by-default decision. Corrections preserve history, and conflicting evidence cannot become a usable holding.
5. Preview the entire batch. The server rehearses the actual atomic completion transaction, checks deferred constraints, and rolls back all preview effects. A successful preview carries an encrypted five-minute completion envelope bound to the original owner and workspace context.
6. Complete the preview. The server validates the session and current financial baseline again under the owner lock. All rows, snapshot revisions, explicit choices and the receipt commit together. Exact retries within the preview lifetime return the existing receipt without adding holdings. After an uncertain response, reload and inspect the receipt before retrying; the browser never retries writes automatically.

Preview is not a reservation. Any intervening financial change can invalidate it. It cannot authorize access by itself: completion still requires the active MFA session, signed CSRF and matching workspace context. Revocation, expiry, disabled ownership and replacement sessions prevent publication. A source or mapping conflict returns a generic review conflict without exposing SQL or provider diagnostics. Authentication failures lock the browser rather than masquerading as a review conflict.

## HTTP and resource boundary

All operations are POST requests under `/api/v1/finance`, with exact same-origin/Host checks, no query parameters or bearer credentials, duplicate-header/cookie rejection, strict JSON, no-store responses and server-derived ownership. Bodies and previews are never logged or persisted in browser storage. Financial responses are capped at 256 KiB.

| Endpoint | Purpose |
| --- | --- |
| `investments/query` | Bounded account positions, instrument identity and current resolved snapshot choices |
| `snapshot-review/query` | Current snapshot batch queue with keyset pagination |
| `snapshot-review/inspect` | Whole batch, effective row decisions, current mappings and optional completion receipt |
| `snapshot-review/account-mapping` | Explicit account target with expected mapping revision |
| `snapshot-review/instrument-mapping` | Explicit instrument/listing target with expected mapping revision |
| `snapshot-review/position` | Idempotent owned account/instrument/holding-form position creation |
| `snapshot-review/decide` | Include, exclude or reopen an uncompleted batch occurrence |
| `snapshot-review/preview` | Bounded snapshot-only completion manifest and rollback rehearsal |
| `snapshot-review/complete` | Validate the encrypted envelope and atomically complete or return its receipt |

Read pages contain at most 100 items; the browser uses 25-item account, investment, batch and instrument pages. Inspection and completion cover at most 100 rows as one batch. The browser loads at most 100 positions, snapshots and choices for a review context; if any context page has a continuation, completion is disabled with an explicit limit message. Larger documents cannot be silently divided or presented as complete.

All ordinary requests retain the 4 KiB body limit. Only the exact preview path permits 64 KiB, and only the exact completion path permits 128 KiB. Both the Python boundary and local HTTPS gateway enforce these exceptions. The five-second receive deadline, strict JSON and authentication rules still apply. Streaming proxy behavior avoids request-body files. No file upload or provider network request is introduced.

Preview keys are generated in memory per application worker and separated from every durable encryption key. Restarting or routing to another worker invalidates the preview safely; reload and prepare again. This is suitable for the current single-worker package, not a claim of multi-worker preview continuity. Receipts and existing evidence survive through the existing database/recovery format. There is no migration or new durable secret.

## Investment display

Only a currently resolved, active selected snapshot supplies the position quantity. Stale, cancelled, archived, unselected or conflicting choices show unavailable amounts. Multiple choices are not summed. Exact decimal strings retain their supplied precision, including zero; missing values remain missing. Native prices are source observations, not a current market valuation.

INR/USD preferences remain visible, but these views explicitly retain native source currencies while conversion is unavailable. There is no fictional FX rate or relabelling. Separately selected dated quote/NAV and FX valuation, aggregate portfolio totals, performance and tax reporting remain subsequent work. Snapshot changes do not create purchases, dividends, fees, lots or cash movements.

Amounts are masked across holdings, details, source inspection and correction evidence. Locking, sign-out, inactivity, context replacement or leaving the protected shell unmounts the financial views; late responses cannot repopulate the previous workspace. A failed refresh removes displayed prior amounts while preserving the database evidence. Identifiers and values do not enter URLs, local/session storage, analytics or console output.

[Step 6E.1](source-history.md) adds source-history coverage inspection from a selected snapshot. It preserves reported periods and replacement lineage without promoting source claims to verified transaction history.

## Verification and images

Tests exercise encrypted preview tampering/expiry/session binding, bounded manifests, strict browser boundaries, dry-run rollback, exact completion replay, exclusions, session/owner loss after writes, overlap correction and owned reads. Frontend tests cover exact values, native currencies, masking, incomplete choices, explicit row/position review, receipts, error privacy and late-response rejection. Browser verification uses fictional responses, checks keyboard operation, reflow and WCAG contrast/accessibility, and verifies empty browser storage and sign-out clearing.

| View | Desktop | Mobile |
| --- | --- | --- |
| Holdings, light | [Image](images/connected-investments/holdings-1440-light.png) | [Image](images/connected-investments/holdings-390-light.png) |
| Holdings, dark | [Image](images/connected-investments/holdings-1440-dark.png) | [Image](images/connected-investments/holdings-390-dark.png) |
| Detail, light | [Image](images/connected-investments/detail-1440-light.png) | [Image](images/connected-investments/detail-390-light.png) |
| Detail, dark | [Image](images/connected-investments/detail-1440-dark.png) | [Image](images/connected-investments/detail-390-dark.png) |
| Review, dark | [Image](images/connected-investments/review-1440-dark.png) | [Image](images/connected-investments/review-390-dark.png) |

No hosted Supabase project, real INDmoney account, real statement or account-specific schema was used. The local package rehearsal checks transport/resource boundaries and the locked shell; it does not certify authenticated financial throughput or live provider compatibility.
