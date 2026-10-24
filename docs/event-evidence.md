# Provider transaction identity and corroborating evidence

[Step 4F.1](financial-data-plan.md) adds internal [event evidence services](../backend/trading_db/event_evidence.py), [protected reference custody](../backend/trading_db/provider_keys.py), and migration [0013_event_evidence](../backend/migrations/versions/0013_event_evidence.py). A reviewed source row can describe an existing event when a supplied provider transaction reference and its economic details agree. This increment does not complete a batch, establish reconciled balances, parse a file or expose financial writes over HTTP.

## Matching boundary

Identity is scoped by owner, source account, event kind and exact provider reference. Reference strings are bounded ASCII and case-sensitive; no trimming or provider-specific normalization is inferred. A future parser must establish that its reference identifies a transaction within that scope. Labels, dates, amounts, row similarity and document digests cannot establish that identity. Two source accounts remain separate even when mapped to one canonical account; cross-provider alias proof is separate work.

Without a reference, existing normalized-row persistence applies. Two identical legitimate payments remain two events. Different references also remain distinct. Retrying the same normalized row returns its earlier result. A recorded normalized row cannot silently acquire a different identity or change from referenced to unreferenced persistence. Batch completion must separately check overlapping source occurrences across normalization versions; this primitive alone does not complete or deduplicate an import.

For a known identity, compare canonical account, position/instrument, event kind, posted/pending state, supplied trade/settlement/booking/value dates, and the complete set of component roles, exact amounts, currencies and missing reasons. Numeric equality permits `12.30` and `12.3` to corroborate the same event; each original source string remains in its immutable staged evidence. Missing components differ from explicit zero or a component with a missing reason. No floating-point conversion or ambient decimal rounding participates.

Matching creates an immutable evidence link to one event revision without adding cash or quantity movements. Changed economics under the same identity conflict. An explicit existing event correction must first record the change; subsequent matching evidence can corroborate the corrected current revision. Cancelled events cannot receive a new corroboration. Historical exact retries return their original link and event revision after later correction or cancellation, preserving what was recorded at that time.

## Privacy and key custody

References use independently derived provider-event HMAC matching and AES-GCM encryption purposes within the existing versioned [financial identifier key ring](accounts-source-mappings.md#private-references-and-keys). These purposes are separate from account-reference encryption, matching and key checks. Authentication covers owner, identity ID, source account, kind, key version and fingerprint. Fresh random nonces prevent deterministic ciphertext. Plaintext references are not stored in SQL columns, URLs, logs or object representations.

Before matching, the service authenticates all bounded owned provider envelopes, including their match indexes, and rejects duplicate decrypted identities. Missing/wrong old keys or damaged ciphertext cannot turn a lookup miss into another event. The service compares exact decrypted references as well as the scoped identity; a digest alone is insufficient.

`EventEvidenceTransaction.rotate_references()` re-encrypts provider references to the active key version atomically and advances database-assigned custody revision/time. Account references have their own rotation operation. Rotate both categories before retiring an old key; preserve all required versions until every envelope has moved. Key rotation changes custody only, retaining event IDs, economic versions and evidence links. Restore validates both categories against separately recovered keys before writing records.

## Database invariants

`event_provider_identities` binds one protected identity to an event's immutable first revision. `event_evidence_links` binds each corroborating source occurrence and exact review revision to its event revision. Both tables have forced active-owner policies, composite owner foreign keys, restricted inserts, database-assigned audit metadata and no runtime deletion. Only the identity's four custody fields permit runtime updates; rotation must advance its key version. Authentication-role reads are denied.

SQL verifies source-account/kind agreement, included review and mapping context, current runtime target, exact economic equality and exclusive source consumption. An event's original row may also carry its own identity link; a different event, lot or snapshot cannot consume a linked row. Linked review decisions cannot be reopened. Runtime writes and rotation share the established owner lock, including direct SQL. Deferred integrity checks allow recovery of validated historical records in dependency order; runtime choices still require current evidence when inserted.

The internal service bounds each new table to 1,000 records per owner, enforced in SQL too. Reads default to 25 and allow at most 100 with opaque cursors. A failed link or key check rolls back the event, identity and evidence writes in the same transaction. Concurrent equal references produce one event; a changed payload conflicts. No external provider or file I/O occurs under the lock.

## Recovery and remaining work

Recovery format **9** covers **36 application tables**: 34 durable and two intentionally omitted session/admission tables. The separate-cluster encrypted drill restores protected provider identities, custody revisions, primary/corroborating links and original event revisions for two owners alongside all existing history. It compares durable rows, grants, constraints and policies, validates recovered keys and keeps old sessions revoked. Earlier objects require their matching release/schema before forward migration. Populated provider-evidence tables cannot be downgraded.

[Contract tests](../backend/tests/test_provider_keys.py) exercise key/scope substitution, tampering, unavailable keys and domain separation. [Database tests](../backend/database_tests/test_event_evidence.py) cover exact reuse, legitimate repetition, changed economics, correction/retry history, owner isolation, direct SQL, concurrency, rotation, rollback and migration safety. The [recovery drill](../backend/database_tests/test_recovery.py) includes both tables. All fixtures are fabricated.

Step 4F.2 adds source and combined-state reconciliation contracts. Step 4F.3 adds bounded atomic batch completion with durable idempotency and immutable receipts. A matching event alone does not attest complete history, reconcile a statement or resolve lot/snapshot overlap.
