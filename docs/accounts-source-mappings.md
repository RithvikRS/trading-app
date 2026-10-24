# Accounts and source mappings: Step 4B

Implemented in [trading_db.accounts](../backend/trading_db/accounts.py), [identifier custody](../backend/trading_db/account_keys.py), and migration [0006_accounts_sources](../backend/migrations/versions/0006_accounts_sources.py). These are internal services using the existing trusted owner transaction boundary. No financial route, statement parser, provider connection, real-data seed, or frontend flow is introduced. The protected workspace remains empty until its complete data flow is implemented.

## Account identity

Canonical accounts use random UUIDs. Their labels never decide whether records refer to the same account. Accounts with identical labels can coexist. The internal service exposes no edits to account kind, institution, market, label, or declared currencies; currency membership is append-only at the database boundary. Labels are 1–64 ASCII letters, spaces, periods, parentheses, or hyphens, beginning with a letter. Use neutral labels such as “Savings”; never put a name, account number, or folio reference in a label.

| Kind | Institution | Market | Compatible source namespaces |
| --- | --- | --- | --- |
| Bank | HDFC | India | `hdfc_statement` |
| Bank | SBI | India | `sbi_statement` |
| Brokerage | INDmoney | India | `indmoney_india` |
| Brokerage | INDmoney | United States | `indmoney_us` |
| Mutual fund | Fund registrar | India | `indmoney_funds`, `cas`, `advisor` |
| Employee stock | UBS | United States | `ubs_espp` |

Each account declares one or both of INR/USD explicitly. Currency membership describes supported native evidence; it does not create cash, convert values, infer a balance, or prove a provider supports that currency. Actual parser coverage must establish the declared set. A deferred database constraint requires at least one currency at transaction commit. Unsupported currencies and duplicate memberships fail.

A source account identifies a reference within one owner and one source namespace. For example, a fabricated CAS folio and advisor reference can explicitly link to one canonical mutual fund account. Distinct references remain distinct until mapped; a matching name, partial identifier, or similar balance cannot merge them. Same-reference repeats within that namespace return the existing source. Providers and markets remain separate namespaces.

## Mapping and archive history

Every link, correction, and unlink appends a mapping revision. Revision one is the initial link; later revisions refer to the immediately preceding revision. Composite foreign keys and a primary key prohibit missing predecessors and branching revisions. The current mapping is the highest revision. An unlink is explicit, with no account reference; it cannot be an initial mapping. Repeating the current link with its current expected revision returns that revision without appending another row.

Changes require the expected current revision. A stale change fails with the same sanitized unavailable/conflict error used for unknown and foreign resources. Account/source changes serialize per owner with a transaction-scoped advisory lock; database uniqueness remains the final guard. Each mutation has a savepoint, so catching a failed operation inside a larger transaction cannot retain its partial writes. An outer failure rolls back the entire transaction. There is no provider or file I/O under these locks.

Archive advances the account revision and retains its currencies, sources, and all mapping history. Archiving is final in this increment. Existing links remain historical evidence; new links to an archived account are rejected. Archive does not rewrite, unlink, or delete financial history. Readers of later financial records must use their recorded mapping revision, not silently reinterpret evidence using today's link.

## Database boundary and limits

The four durable tables are `financial_accounts`, `account_currencies`, `source_accounts`, and `source_account_mappings`. Every row has an owner; child references include both owner and parent ID. All tables enable and force row-level security with active-owner read/write policies. The runtime identity cannot change ownership, account identity, source namespace, audit timestamps, or mapping history. It has narrowly scoped insert/update columns and no delete/truncate permission. The authentication identity has no financial table access. The schema owner is subject to forced RLS too; recovery uses the existing isolated administrative test identity.

`AccountDatabase.transaction(owner_id)` accepts an already authenticated owner UUID. It does not authenticate requests or accept an owner field from a request payload. It reuses the existing role checks, transaction-local owner setting, active-owner lookup, and pool cleanup. Transaction objects cannot be used after exit. Database errors are replaced by a fixed message; no reference, SQL parameter, constraint detail, or foreign-owner existence is returned.

Account/source pages default to 25 and cap at 100, ordered by opaque UUID; mapping history pages use descending revision with an exclusive cursor. Unknown and foreign resources have the same absent result. Services cap accounts, source accounts, and mapping revisions at 1,000 rows per owner/table. Source lookup and rotation inspect at most 1,001 source rows and fail if the cap is exceeded. These are initial bounded internal services, not a capacity claim for a large imported portfolio. The separate recovery rehearsal caps each table at 1,000 rows across all owners.

## Private references and keys

External references are exact ASCII strings of 1–128 characters: an alphanumeric first character followed by alphanumeric, period, underscore, slash, or hyphen characters. Leading zeros and case are significant. These are normalized project contracts, not verified HDFC/UBS/CAS export rules. A future parser must preserve source evidence and explicitly normalize supported formats before this boundary; an unsupported identity stays in review.

Matching uses HMAC-SHA-256 over the owner, source namespace, and exact reference. A separate AES-256-GCM ciphertext retains the reference so that it can be verified and re-fingerprinted during rotation or recovery. HKDF-SHA-256 derives separate matching, encryption, and key-check subkeys from an independent random 32-byte master key. Ciphertexts use fresh 12-byte random nonces and bind owner, source ID, namespace, key version, and fingerprint as authenticated associated data. No unkeyed identifier hash or plaintext reference is stored. [Authenticated encryption](https://cryptography.io/en/latest/hazmat/primitives/aead/).

Each row has a version and owner-scoped key check. Before matching or creating a source, every existing version for that owner must be available and correct, and every stored reference is authenticated. A damaged lookup fingerprint cannot turn an existing identity into a new source. Missing/wrong keys fail closed without creating replacement sources. A matching fingerprint is also checked against the decrypted exact reference; a digest collision cannot merge two different identities. Public internal source views contain only opaque ID, namespace, and revision. Fingerprints, ciphertexts, and references are never exposed by a route or written to logs.

The key ring holds at most eight distinct keys with positive 32-bit versions. The highest loaded version is active; version numbers cannot be reused with new material. Session keys and encrypted backup keys are separate and must never be reused as financial identifier keys.

### Local custody and rotation

From `backend/` in the locked environment, explicitly initialize the first local key when a local account service is needed:

```powershell
uv run --locked python -m trading_db.account_keys 1
```

This exclusively creates ignored `.cache/finance/keys/v1.key`, using the existing private directory ACL setup on Windows or owner-only permissions on Unix. It prints no key. Existing keys are never overwritten, and startup/lookup never generates one. The key loader rejects missing, oversized, symlinked/junction paths and insecure Unix modes. On Windows, protect recovered directories/files with the same account/SYSTEM ACLs before loading; the loader does not independently audit every Windows ACL entry. No production key was created by the automated tests.

Load a ring with `load_keys(directory, active=1, versions=(1,))`, then pass it to the internal account store. To rotate: create version 2 separately, recover/verify both keys, load `(1, 2)` with active 2, and call `rotate_references()` in each owner's transaction. It authenticates every ciphertext before changing any row, rejects duplicate exact identities, and re-encrypts/re-fingerprints atomically. Source IDs and mapping revisions stay stable; source revisions advance. A retry rewrites zero rows. Stop source mutations using old-only key rings before rotation; they fail closed once newer versions exist.

Retain old keys until every owner's rows have been rewrapped and every retained backup needing the old key has expired or been restored and re-exported safely. Loss of a required key is unrecoverable without a separately retained copy. Never substitute a new key under an existing version, blank a reference, or remove a failed row to resume matching. Separate off-host key custody, rotation scheduling, and production secret mounting remain deployment work.

## Migration and recovery

Apply the normal [local migration command](database-foundation.md#commands-and-lifecycle) to reach `0006_accounts_sources`. Existing identities, sessions, and preference revisions are preserved; no accounts or keys are seeded. Reapplying the migration is a no-op. Disposable tests exercise upgrade, downgrade/re-upgrade, and complete rollback after an injected mid-migration failure. Destructive downgrade remains restricted to disposable databases.

Step 4B introduced recovery format **2**, covering eleven application tables: nine durable tables, with sessions/admissions explicitly omitted. It includes all four account tables, encrypted references, key versions, currencies, archive state, and mapping predecessors. Parent rows restore before children; the mapping predecessor foreign key is deferred so backup row order cannot corrupt history. The outer encrypted object still binds schema revision and migration-source digest.

Export and restore require a separately supplied identifier key ring whenever source references exist. Every ciphertext and exact source identity is checked before restore writes. Wrong/missing keys, duplicate identities, altered context, uncovered columns, incompatible manifests, or constraints abort without partial data. Keys themselves are never included in the database object. The separate-cluster drill recovers the encrypted object, its encryption key, and identifier key independently; compares all durable rows, revisions, constraints, column/table grants and policies; and denies old sessions.

Format 1 objects must be restored using their matching repository/schema revision, then upgraded forward with the committed migrations. Do not edit a manifest version/digest or relabel an old object. The format-2 reader intentionally rejects format 1. The limits and hosted recovery gaps in [local packaging](local-packaging.md#encrypted-foundation-recovery) still apply.

## Verification

Synthetic tests cover account combinations, exact-reference matching and collision handling, owner/provider separation, authenticated-context tampering, unavailable keys, exclusive private key creation, forward rotation, mapping corrections/unlinks, archives, stale/concurrent writes, bounded pagination, direct-SQL denials, transaction/savepoint rollback, pool reuse, migration preservation, and encrypted restore into a second PostgreSQL cluster. Local and CI check results are recorded with this increment's PR. No real statement or hosted Supabase verification is represented by these tests.

[Step 4C](instrument-identities.md) subsequently adds instruments/position identities and extends the current recovery format to 3. Older objects retain their matching-release restoration requirement.

The local development database was migrated to `0006_accounts_sources` on 24 October 2026. All eleven application tables remain empty; no owner, account, source, or identifier key was seeded.
