# Financial events and native movements: Step 4D.2

The [internal event service](../backend/trading_db/events.py) records one included source occurrence as an immutable financial event, exact components and native cash/quantity movements in one transaction. Migration [0009_financial_events](../backend/migrations/versions/0009_financial_events.py) adds four owner-scoped tables. This is a persistence primitive for later reviewed completion; there is no upload, parser, trade execution, HTTP mutation route, balance calculation or connected frontend.

## Supported economics

| Kind | Quantity movement | Native cash movement |
| --- | --- | --- |
| Buy / subscription | Positive supplied units | Negative supplied net cash |
| Sell / redemption | Negative supplied units | Positive supplied net cash |
| Dividend | None | Supplied nonnegative net cash |
| Fee / withholding | None | Supplied nonpositive cash |
| Cash movement | None | Supplied signed cash |

Source spelling and exact numeric values remain separate. Unit precision is at most 12 fractional digits, cash 2, and monetary evidence 8; finite magnitude remains below 10¹⁸. The [staged-value contract](import-staging.md#rows-and-exact-values) also governs event components. Unknown optional fees remain null with their missing reason; explicit zero remains zero. Gross dividend, net cash, fee and withholding are independent components. Only net cash creates the dividend's cash movement, preventing gross/net double counting.

All monetary components in a simple event use the same native currency; it must match the mapped fund/listing currency when supplied. Cross-currency interpretation is unsupported here. Quantity × unit price is not silently substituted for independent settlement evidence. Gross/fee/net reconciliation, complete activity checks, economic deduplication and batch receipts remain [Step 4F](financial-data-plan.md#review-completion-and-deduplication).

Trade, settlement, booking and value dates retain their independent supplied values. Trades require a trade date; ordinary cash activity requires a booking date. An absent booking date is not inferred from settlement or trade date. Pending activity is explicitly identified by source evidence. Movement reads require a `posted` or `pending` filter, so pending entries cannot enter booked activity through an omitted filter. No opening balance, complete holding, short position or investment return is inferred from this event history.

## Evidence, positions and retries

Recording takes an opaque row ID, expected review revision and an explicit existing position for security-associated activity. It reads the immutable normalized economics rather than accepting a second amounts payload. The source must be currently included with current observation/batch and account/instrument mapping revisions. The account must be active. A position must belong to that owner, mapped account and instrument; folio/demat/custody form is never guessed. Snapshot and lot rows cannot become events or synthetic purchases.

The event retains its exact review revision and thus its source, observation, normalization and mapping lineage. Unique owner/source occurrence identity prevents applying one occurrence twice. An exact retry returns its historical event even after later archival or source supersession. A different expected review revision or position conflicts. Similar amounts/dates and separate source occurrences remain separate; this narrow replay rule does not identify duplicate economic events across sources.

Once used by an event, a row's review decisions are locked against include/exclude/reopen. Revised source evidence may still be staged, but cannot erase the existing event. Source review state alone is not a financial completion receipt. Initial event versions are immutable; sourced lot evidence, correction reasons, effective-version changes and cancellation treatment follow in Step 4D.3. The current service does not expose a correction operation.

## Database and transaction boundaries

`financial_events`, `event_components`, `quantity_movements` and `cash_movements` have forced active-owner policies and composite owner references. Runtime has SELECT and explicit INSERT columns, with no economic updates/deletes, truncation or audit-time assignment. The authentication role has no access. Parent/position/account references cannot cross owners. Financial record representations and failure messages contain no amounts or source identifiers.

The trusted owner transaction and shared account mutation lock serialize competing writes. Database triggers acquire the same lock for event/review/evidence changes, mapping changes and account archival, including direct restricted-role SQL. This closes the race between recording an event and concurrently changing its reviewed context. A savepoint covers the entire operation. Deferred constraints verify exact source kind/state/dates/components, the referenced inclusion/mapping context, exactly one matching native cash movement and the required quantity movement. Missing, altered or extra components/movements fail the transaction, including direct restricted-role SQL writes. Source decimal text must match even when a differently spelled decimal has the same numeric value.

Reads default to 25 and cap at 100, ordered by opaque event ID with exclusive cursors. Account event and movement reads select the latest event version. Storage remains bounded to 1,000 rows per owner/table. These are small-workspace limits, not production-volume or complete-ledger claims.

## Compatibility and recovery

The migration preserves existing records. Older staged rows receive unknown (`null`) posting state, never an inferred `posted` value. Their batches retain contract version 1 and their original digest. New batches use version 2, whose canonical content includes posting state. Reading a batch verifies the digest with its stored version. Changing unknown state to posted/pending requires new explicit normalized evidence and a new normalizer version; old inclusion does not authorize recording an event with unknown state.

Recovery format **5** covers all 26 application tables: 24 durable and the two deliberately omitted session/admission tables. It includes both batch contract versions, explicit posting state, event versions/components and movement provenance. The separate-cluster synthetic drill restores posted and pending events, fractional units, original decimal strings, unknown fees and prior review history alongside owner constraints, grants and policies. Separately recovered identifier keys remain necessary and former sessions remain revoked.

Formats 1–4 require their matching release/schema for restore followed by tested forward migrations. The reader never relabels an older object. [Recovery scope and hosted gaps](local-packaging.md#encrypted-foundation-recovery) remain unchanged: this is a bounded disposable exercise, not production backup infrastructure.

Synthetic verification covers all supported kinds, pending isolation, net dividend treatment, source/review/position conflicts, exact replay, concurrent recording, rollback after the last write, direct-SQL integrity and role denial, legacy upgrade/digest preservation, migration failure and encrypted recovery. Actual local and GitHub check results are recorded in the PR. Next is [Step 4D.3: lot evidence and corrections](financial-data-plan.md#delivery-increments).
