# Protected import and review inspection

Step 4G.3a exposes retained source observations, normalized batches, staged rows and review history through the authenticated financial API. These reads support inspection; an included row is saved review intent and does not imply a completed transaction or portfolio balance.

## Routes and pagination

All routes are `POST /api/v1/finance/` queries with strict JSON bodies, the active MFA session and its bound CSRF token. Query strings and unknown fields are rejected. Limits default to 25 and allow 1–100 records.

| Route | Required fields | Cursor and ordering |
| --- | --- | --- |
| `imports/observations/query` | `source_id` | `after`: opaque observation ID, ascending |
| `imports/batches/query` | `observation_id` | `before`: positive revision, descending |
| `imports/rows/query` | `batch_id` | `after_occurrence`: original source occurrence, ascending |
| `imports/rows/inspect` | `id`: staged row | Single row |
| `imports/reviews/history` | `id`: staged row | `before`: positive review revision, descending |

Pages return `items` with `next_after`, `next_before` or `next_after_occurrence`; null means the page has no further entries. Source occurrences can have gaps and are not row offsets. Required parents outside the current owner and unknown parents both return the same 404 response. Existing empty histories return empty pages. Pagination is consistent within each request; later requests can observe newly appended evidence or decisions.

## Evidence and effective review state

Observation metadata retains the original coverage, paired source period and predecessor link. `is_current` means no replacement observation exists. Batch `is_current` means the latest normalization of that observation; `source_current` separately identifies whether the observation itself has been replaced. Historical batches and their original normalization version remain inspectable.

Rows retain supplied decimal strings and native currencies, separate source dates, explicit posting state, missing-value reasons and source occurrence. Invalid or incomplete candidates can have no components. An opaque instrument identifier links to the identity model; private provider identifiers are never returned.

`blocked_reason` records the original candidate evidence. `status` and `issue` describe its effective state now, using the same rules as the persistence service:

- `reviewable`: valid evidence without a current include/exclude choice, including reopened rows.
- `included`: an include decision with valid current account and instrument mapping context.
- `excluded`: an explicit exclusion and its retained reason.
- `blocked`: missing, unsupported or incompatible evidence, unresolved identity, or stale mapping context.
- `superseded`: a replaced observation or normalization; earlier review intent remains visible.

The latest decision carries its original source and mapping revisions. Review history is immutable and newest first, with an explicit `is_current` flag. Current mapping changes can invalidate inclusion without rewriting that decision. Exclusions do not make incomplete evidence suitable for a complete financial ledger.

## Security, bounds and recovery

The shared [financial read boundary](financial-reads.md) enforces exact host/origin, MFA, CSRF, revocation, no-store responses and an owner-scoped read-only transaction. Responses use explicit fields and strict schemas, omitting owner IDs, raw documents, digests, fingerprints and encrypted custody fields. A financial query failure preserves a valid browser session and returns a generic unavailable response.

Row inspection validates the normalized batch checksum once, then reuses the persistence service's effective-state rules. A batch is bounded to 100 rows and 800 components; overflow sentinels reject excess data. Components load in one bounded query, with row counts, component counts, contract versions and canonical integrity checks retained. Page query counts do not grow with the number of returned rows. The shared response size ceiling still applies.

Tests use fabricated records and disposable PostgreSQL. Coverage includes exact and missing values, sparse occurrence pagination, replaced evidence, account/instrument remapping, uniform owner denial, browser protections, bounded maximum pages, unavailable responses and comparison with existing domain status. The separate-cluster encrypted recovery drill compares restored import and review responses after fresh sign-in. No migration, privilege, dependency or recovery-format change is required.

[Step 4G.3b](completion-receipt-reads.md) adds completion receipts and frozen reconciliation comparisons. File parsing, financial mutation routes and connected interfaces remain the later complete data flow in Stage 5.
