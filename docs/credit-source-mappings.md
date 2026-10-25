# Credit source handles and mapping history: Step 9B.3

The internal credit-source service adds application stream identities and immutable mappings to the [billing-account registry](credit-account-identity.md). A handle is an explicitly selected local stream, not a verified HDFC issuer identity. Two identical source families remain two handles; neither their family nor their target account merges them. No real HDFC export layout, provider access, ingestion, HTTP route or screen is introduced.

## Minimized identity

Each handle contains only a server-generated UUID, server-scoped owner, the fixed `hdfc_credit_statement` family and a server creation timestamp. The service has no external-reference, name, filename, narration, card-number, last-four, ciphertext or arbitrary-metadata input. The existing `hdfc_statement` bank namespace and generic encrypted-reference store are unchanged. Encryption of an arbitrary identifier would not establish that it is safe card evidence.

A future verified normalizer must define minimized source identity, or require explicit stream selection. Last four digits, a label or a matching amount cannot identify a billing relationship. Separate handles can contain overlapping evidence; this increment provides neither document replay nor economic deduplication.

## Mapping and lifecycle

Initial linking, correction and unlinking append revisions with exact predecessors and fixed reasons. The current expected revision is required; stale requests fail. Repeating the current binding with its current revision returns the same revision, but a linked target must still be active. Initial unlink is invalid. Multiple handles may explicitly target one billing account. Every historical revision remains readable.

`mapping()` returns retained intent, including unlinked or archived targets. `resolve()` returns only the latest mapping to an active billing account in one SQL statement. Resolution is a point-in-time read, not a future authorization to post. Archival retains all source and mapping history. Future financial records must bind their original source handle and mapping revision instead of being reinterpreted through today's mapping. These are application decisions, not issuer-effective physical-card membership dates.

## Ownership and bounded writes

Both tables have composite owner keys and foreign keys, migrator ownership, enabled/forced active-owner RLS, server timestamps and narrow SELECT/INSERT grants. Runtime cannot update, delete, truncate or install triggers. Authentication and PUBLIC roles have no access. The internal service requires a separately authenticated owner; fixed unavailable/conflict errors reveal neither foreign identity existence nor supplied values. Immutable service representations omit private identities.

Writes share the billing-account owner lock and use savepoints. Target-account row locks serialize link validation with direct SQL archival. SQL guards independently enforce immediate current predecessors, nonredundant mapping revisions, active same-owner targets and admission quotas. Runtime inserts require read-committed isolation; repeatable-read and serializable inserts fail rather than using stale admission snapshots. Trusted bootstrap recovery retains its structural-constraint path. There is no external I/O under these locks.

Fresh runtime checks verify the active owner and transaction-local context after the owner advisory lock and again after any mapping target-row wait. A deactivation committed during those waits rejects the insert; a fresh RLS-filtered count of zero cannot authorize it. These checks protect the direct-runtime/internal registry boundary. Session revocation via `revoke_owner` does not deactivate `owners.is_active`, and this slice does not introduce a shared lock that globally serializes deactivation with transaction commit.

Each table admits at most 1,000 records per owner, including all mapping history. Handle reads use ascending UUID keysets; history uses descending exclusive revision cursors. Pages default to 25 and cap at 100. Unknown and foreign identifiers have the same absent results. No balances, limits, statements, movement components or physical-card memberships are stored.

## Migration and recovery

Migration `0020_credit_source_mappings` follows `0019_credit_billing_accounts`. A downgrade refuses to discard any source handle or mapping history, including unlinked and archived-target history. Prior migrations remain unchanged.

Recovery format 16 covers 46 application tables: 42 durable tables and four explicitly omitted live session/admission/connector tables. Handles restore before mappings, and the deferred predecessor key preserves history independently of row ordering. Two-owner recovery includes unmapped streams, shared targets, corrections, unlink history and archived targets. Existing session invalidation and owner/grant/policy verification remain in force. No additional identifier key is required because no external reference is retained.

The existing 4 MB plaintext and 1,000-row-per-table recovery limits remain unchanged; that row limit spans all owners. Older objects require their matching repository/schema followed by a tested forward migration. The investment completion baseline remains unchanged; future credit completion must explicitly extend and version its protected input scope.

## Verification and next boundaries

Focused synthetic tests cover strict identifier/revision/page inputs, private representations, independent streams, two-owner and inactive-owner denial, mapping retries and history, archive resolution, rollback, direct SQL grants/constraints, concurrent revisions, admission quotas and stale isolation snapshots. Owner-deactivation regressions observe the blocked backend through PostgreSQL lock state, exercise both advisory and unchanged target-row waits, retain an unaffected active-owner control and inspect committed rows through bootstrap. Migration tests cover interruption, repetition, empty downgrade/re-upgrade and populated downgrade denial. Recovery adds source and mapping assertions to the separate-cluster drill. The focused database, migration and encrypted-restore checks passed in a dedicated disposable service; no provider compatibility is claimed.

Credit-specific minimized source observations and normalization lineage must precede durable statement evidence. Later values must preserve the Step 9B.1 exact contracts: independent dates, original decimal precision, missing versus zero, separate statement/current evidence and explicit liability direction. Physical-card membership remains optional for billing-level statements. No paid/overdue status, remaining payment, spending, bank matching or completeness claim is derived here.

Local non-Docker validation passed: 106 focused unit/recovery tests, Ruff lint/format, strict mypy for the service and recovery module, 892 documentation links and diff whitespace checks. All 110 focused PostgreSQL tests passed, including 38 source/migration cases, the billing-account identity suite, encrypted recovery and INDmoney regressions. The bounded disposable run exited successfully and removed its containers, network and credential directories. The complete integrated local verification gate remains separate.

The combined owner-deactivation reproduction first demonstrated four committed-write failures; all five lock-wait regressions now pass, including the previously protected mapping advisory-lock path. Fresh owner checks preserve the fixed errors, active-owner controls and trusted restore behavior described above.
