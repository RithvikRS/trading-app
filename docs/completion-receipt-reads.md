# Protected completion receipt and comparison reads

Step 4G.3b exposes immutable completion effects and frozen reconciliation evidence through the [protected financial API](financial-reads.md). A receipt describes a successful historical completion. It does not assert that the current portfolio is unchanged, that a saved selection is still usable, or that another import would succeed now.

## Queries

All routes are strict JSON `POST /api/v1/finance/` queries using the active MFA session and its bound CSRF token. Page limits default to 25 and allow 1–100 records. UUID cursors are canonical nonzero IDs, ordered ascending; pages return `items` and `next_after`, which is null at the end.

| Route | Required fields | Optional fields | Result |
| --- | --- | --- | --- |
| `receipts/query` | None | `batch_id`, `limit`, `after` | Owner's immutable receipt metadata, optionally for one owned batch |
| `receipts/inspect` | `id` | None | One receipt's metadata |
| `receipts/rows/query` | `receipt_id` | `limit`, `after` | Historical row operations and effects |
| `receipts/scopes/query` | `receipt_id` | `limit`, `after` | Native comparison scopes and original periods |
| `receipts/scopes/inspect` | `id`: scope | None | One frozen source/combined comparison |
| `receipts/inputs/query` | `scope_id`, `side`, `part` | `limit`, `after` | Original inputs for one side and part |

Required foreign and unknown parents share the same 404 response. Owned empty scopes return empty pages. Omitted `batch_id` lists only the current owner's receipts. `side` is `source` or `combined`; `part` is `opening`, `activity` or `closing`. Inputs paginate by their original reference ID within that explicit side and part. These pages do not replay a completion or mutate review state.

## Historical meaning and exact values

Receipt metadata contains its opaque ID, original batch and revision, mode, coverage, UTC creation instant, row count, selection count and comparison scope count. Limited coverage has no comparison scopes. Reconciled mode requires complete activity and retained comparisons. The idempotency key, baseline token, canonical request, hashes and private provider references are omitted.

Each completed row's `id` is its source row ID. Its original review revision, operation (`record`, `correct`, `exclude`) and outcome (`recorded`, `linked`, `corrected`, `excluded`) remain explicit. An included effect names exactly one event, lot observation or snapshot with its saved record revision. Exclusions have no financial target. Optional provider identity and source-selection links are opaque IDs, with selection revisions retained. Inspect a record's history to distinguish that saved revision from a later correction.

Scopes identify one account's native cash currency or one position's units, the original source period, date basis, reconciliation rule version and input count. Cash and units never share an equation; INR and USD are never added. Scope inspection returns `scope`, `source` and `combined`. Each side contains the original opening/closing strings, exact posted total, calculated closing, difference and posted/pending counts. Pending activity remains separate from posted totals. Explicit zero remains evidence.

Inspection reconstructs the comparison from its frozen inputs using the persisted rule version and existing exact reconciliation service. It checks the recomputed amounts/counts against the stored summary, validates native precision and the equation, and fails closed on inconsistency. Later event corrections, remapping, replaced observations or changed selections cannot alter these historical inputs. A balanced result applies to the saved comparison at completion time.

Input pages preserve the exact supplied decimal string, evidence date, posting state, original reference and revision, native kind/currency, and explicit source-row/event/snapshot lineage. Source-side revisions identify reviewed source occurrences; combined-side revisions identify financial records. No source timestamp or missing date is inferred. To inspect current evidence or selection validity, use the separate event/snapshot/market endpoints.

## Security and resource bounds

Every route shares exact host/origin validation, active MFA, CSRF, final session/revocation checks, no-store responses and the owner-scoped read-only RLS transaction. Explicit SQL projections and strict schemas omit private custody fields and owner identifiers. Inspection requires no reference decryption. A financial data failure returns the generic unavailable envelope without clearing a valid session.

Receipt listings fetch metadata only. Row/scope/input pages fetch at most `limit + 1` records, and scope counts use an overflow sentinel. One comparison inspection reads at most 1,001 frozen inputs, rejecting overflow or a count mismatch; the persisted limit is 1,000 inputs per scope. It never expands every comparison in every receipt. The shared 256 KiB encoded-response ceiling rejects oversized responses.

## Persistence acceptance

Fabricated PostgreSQL/HTTP cases cover metadata, exact cash and fractional units, separate native scopes, explicit zero and pending counts, exclusions/corrections, historical replay after later changes, pagination, two-owner denial, browser protections, bounded SQL and corrupt comparisons without session loss. A fresh application instance reads the same receipt pages. The separate-cluster encrypted recovery drill compares all financial read families after fresh sign-in and rejects old sessions.

The maximum-batch case measures a 100-row import page, 100 completed effects, 98 combined activity inputs and a comparison with 200 frozen inputs. It writes only route names, counts, response byte sizes, elapsed time and traced Python heap peaks to ignored `.cache/operations/financial-read-sample.json`. Statement counts cover the financial workspace connection; separate authentication registry queries are excluded. These are local synthetic measurements, not Oracle capacity, total process memory or production latency claims. Workspace query-count and response-size bounds are enforced; wall-clock time is reported without a brittle timing threshold.

Step 4's persistence services and authenticated read boundary are complete. No migration, privilege, dependency or recovery-format change is required for these reads. The schema remains `0017_reconciled_completion`, recovery format 13, with 40 application tables and 38 durable tables. Local development remains unseeded; all acceptance records are disposable. Hosted Supabase/provider checks remain separate work. Stage 5 provides the first complete file-import-to-portfolio flow; the protected frontend remains empty until that flow is implemented.
