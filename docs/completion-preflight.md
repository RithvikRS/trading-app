# Completion requests and stale-state protection

Step **4F.3.2a** defines the internal request boundary and database state token needed before atomic import completion. It adds no completion endpoint, receipt or financial write operation. [Step 4F.3.2b](completion-receipts.md) subsequently adds atomic limited-coverage receipt persistence. [Step 4F.3.2c](reconciled-completion.md) binds full source-period reconciliation to immutable comparison inputs.

## Request contract

The strict, immutable [completion contracts](../backend/trading_db/completion_contracts.py) accept a batch identity/revision, an opaque idempotency key, a baseline token, and up to 100 distinct reviewed row choices. Each choice requests recording, correction or exclusion. Corrections require the exact target family, identity, revision and a finite reason. Exclusions cannot request financial effects. Snapshot selections reference included rows explicitly. A remaining-lot row may reference a new acquisition row in the batch; cycles, chains and ambiguous existing/new lot targets are rejected.

Ownership, amounts, source coverage, reconciliation results and a caller-supplied claim of verified state are forbidden. The completion service independently resolves current reviews, mappings, positions and source economics from the authenticated owner's database transaction. These contracts alone do not establish ownership, a valid acquisition, source order or a balanced ledger.

The canonical public manifest contains only opaque identifiers, revisions, finite choices and a boolean indicating whether a private provider reference was supplied. It omits the actual reference and any unkeyed digest of that reference. Two requests with different private references therefore intentionally produce the same public manifest; the completion service must also compare the decrypted protected identity before accepting a retry. A public digest alone is insufficient.

The manifest reader requires an exact canonical JSON representation, a known contract version and a maximum of 65,536 UTF-8 bytes. Unknown/private fields, duplicate JSON keys, duplicate occurrences, noncanonical ordering and inconsistent directives fail validation. Nested copied models are revalidated before serialization. Internal Python requests use UUID instances; a future HTTP route needs its own tested JSON boundary. Private references and validation payloads must stay out of logs.

## Database baseline

Migration [0015_completion_baseline](../backend/migrations/versions/0015_completion_baseline.py) introduces `app.financial_baseline()`. It takes no owner or table-name argument. The restricted runtime role must already hold an active owner context in a read-committed transaction. The function acquires the common financial owner lock, then hashes a bounded, ordered representation of that owner's financial identities and revision histories.

The representation includes accounts/currencies, source identities and mappings, instruments/listings/positions, observations/batches/rows/reviews, events, lots, snapshots/selections and provider evidence links. It excludes source descriptions, amounts, private references, encrypted custody material, prices and display preferences. Key rotation preserves the token; an unrelated financial change for the same owner may conservatively invalidate it. Another owner's changes do not affect it.

Each table read is limited to 1,001 records, and any count above 1,000 fails instead of hashing a truncated view. Parent revisions cover their immutable, database-validated financial components. The migration adds the common insert lock to identity/staging tables that previously relied on their service transaction, so direct restricted-role writes cannot race a baseline guard.

The database function is explicitly `VOLATILE`: after waiting for another writer, its queries observe that writer's committed change. Repeatable-read and serializable contexts are rejected here because they can retain an earlier transaction snapshot. The [internal guard](../backend/trading_db/completion_baseline.py) compares the expected token under the same lock and savepoint as dependent work. Failure rolls back that work; the surrounding transaction may still continue safely. The lock lasts until the outer transaction ends, so callers must keep it short and perform no provider or network I/O inside it.

A baseline is an anti-staleness token, not proof of complete history or a substitute for reconciliation evidence. [Step 4F.3.2b](completion-receipts.md) enforces the token in PostgreSQL and adds receipt identities to the versioned baseline. [Full reconciled completion](reconciled-completion.md) also retains immutable compared inputs. Exact completed retries resolve the original receipt before comparing live state.

## Migration and recovery

The migration preserves all existing rows and the 36-table inventory. Recovery format **11** pins the new schema/function source, still exporting 34 durable tables and omitting the two session/admission tables. Restore older objects with their matching source revision before a tested forward migration. The separate-cluster drill compares both owners' baseline tokens before/after identifier rotation and after encrypted recovery, alongside existing row, constraint, policy and grant checks.

Disposable downgrade/re-upgrade removes/restores the new function and eight insert triggers without losing financial data. Development uses forward migrations only. No hosted Supabase test is implied.

## Verification

Synthetic tests cover private-reference omission, exact manifest parsing, malformed copied models, directive conflicts, owner/role denial, stale token rejection, failed-write rollback, bounded state, key rotation and recovery. Real concurrent PostgreSQL tests hold the owner lock, start a competing statement, verify that it is actually waiting, then commit and check the resulting token. A second race checks that raw identity inserts respect an existing baseline guard.

The current [receipt schema and recovery format](completion-receipts.md#recovery-and-verification) supersede the preflight-only inventory above.
