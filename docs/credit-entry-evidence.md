# Immutable credit entry evidence: Step 9B.6.1

This increment retains only explicit CardEntryValues interpretations under owned credit source/mapping/account provenance. Entry roles, treatment, billed INR and optional original native evidence remain independent of statement allocation, chosen liability, payment status or source-format support. No movement, withdrawal, cancellation, reversal link, import, API or UI is introduced.

## Acceptance contract recorded before implementation

1. Every role/treatment combination, including unresolved+movement denial; posted rows with missing independent dates remain valid; pending posting-date attempts fail through both Python and SQL.
2. Billing nonnegative known/missing values, zero/negative-zero spelling, precision/magnitude bounds and fixed INR; every original group state, INR/USD, nonnegative rules and NULL-safe partial-group rejection.
3. Wrong/counterfeit nested types, cached money/date changes, extra identity/free-text fields and private diagnostics. Explicit original absence must not equal a present-missing original value.
4. Identical explicit target retries, spelling/role/date/currency conflicts, retained historical retries, distinct equal reports and explicit pending-to-posted/other interpretation corrections without added movement rows. A correction to unsupported must remain listable as the latest revision with prior history intact; no withdraw/remove operation or movement/selection change is introduced.
5. All three kinds coexist under one root namespace. Wrong-kind reads are absent; attempts to switch kind/source/account, skip revisions or attach multiple/wrong children fail as bootstrap and runtime. Existing statement/current read/write/retry suites remain unchanged.
6. Direct runtime missing-owner-filter reads, foreign-owner inserts, default child-kind grants, immutable updates/deletes and active-owner policy checks. Bounded pages and closed-unit behavior match existing services.
7. Actual-lock-wait owner-deactivation regressions on both insert boundaries; READ COMMITTED enforcement, stale-snapshot denial, two mixed-kind last-slot races, exact retry at quota, concurrent corrections, archival and remap ordering. Observe worker PIDs/blockers and committed bootstrap state; sleeps alone do not prove ordering.
8. Child failure, deferred integrity failure, interruption and outer rollback leave no partial pair. Runtime child-first remains denied; trusted complete deferred restoration works.
9. Populated 0022 upgrade preserves both older kinds; repeated/injected-failure upgrade, empty round trip and populated downgrade denial preserve exact structure and grants.
10. Two-owner mixed-kind encrypted restore, wrong/missing children, malformed original groups, changed historical binding and old-session denial; original strings and absence distinctions survive byte-for-byte without source inference.


## Stored boundary

The internal `CreditEntryDatabase` accepts a server-allocated root UUID, owned source handle, exact mapping revision and [existing entry value contract](credit-card-values.md). It derives owner and billing account from the authenticated transaction and mapping. The source handle remains the internal HDFC statement family; this does not verify a real export or API format. There are no physical cards, PAN fragments, issuer references, merchant text, descriptions, filenames, caller metadata or statement-membership fields.

The five roles (`posted_debit`, `posted_credit`, `pending_debit`, `pending_credit`, `unresolved`) and three treatments (`movement`, `ambiguous`, `unsupported`) are retained explicitly. An unresolved role cannot claim movement treatment. Pending entries cannot carry a posting date. Transaction and posting dates are optional independent calendar evidence within years 0001–9999; neither date is inferred, ordered against the other or converted to an instant.

Billed cash is nonnegative INR or explicitly missing. Optional original cash keeps its own INR/USD currency, decimal spelling and missing reason. Absent original evidence, present-but-missing original cash and known zero are distinct. The original and billed values are neither converted nor compared. SQL checks preserve these groups with NULL-safe validation; runtime validation rejects wrong nested types and mutated decimal/date caches privately before SQL.

## Immutable history and explicit retries

A caller allocates and retains `new_entry_id()` before `record()`. The initial expected revision is zero; corrections append the next contiguous revision. Every revision freezes its source, exact mapping revision and billing account. A root can never switch between statement, current and entry kinds or move to another source/account. Identical reports with different root UUIDs remain separate.

An exact retry targets `expected_revision + 1` and compares all retained values, including original presence, currency, spelling, dates, role and treatment. It first requires the owner to remain active, the supplied mapping to be current and the account to remain active. A known historical target can replay exactly under that authorization; remapping, unlinking, archival and conflicting payloads do not authorize a new revision or replay. Historical reads remain separate from current write admission.

Corrections may explicitly change pending/posted or debit/credit interpretations. No automatic movement, pairing, cancellation, withdrawal, removal or reversal linkage is created. A correction to `unsupported` remains listable as the latest interpretation with all earlier revisions retained. It does not change bank activity, statement selection, payment status or financial movements.

Account lists return latest entry revisions by UUID keyset, default 25 and maximum 100. They are not chronological history or selected balances. Root history pages use descending revisions with the same bounds. Unknown, foreign and wrong-kind roots are absent through the same interface; returned objects and errors do not print financial payloads.

## Structural and concurrent protection

Migration `0023_credit_entry_evidence` adds one typed child table, `credit_entry_values`, and a nullable stored entry discriminator on the shared observation parent. Three explicit NULL-safe discriminator branches and reciprocal deferred foreign keys require exactly one correctly typed child. Existing statement/current defaults and writer behavior are preserved. Composite mapping and predecessor keys enforce owner/source/account/kind binding and contiguous revisions for trusted restore as well as runtime writes. Runtime requires parent-first admission; trusted restore may insert a complete deferred pair in either order once referenced mappings exist.

The new table is owned by the migrator with enabled and forced owner RLS. Runtime receives only SELECT and the required INSERT columns; it cannot supply the child kind, update, delete or truncate retained evidence. The shared trigger keeps immutable history for trusted roles too. Application and direct runtime writes require `READ COMMITTED`, the shared owner advisory lock, latest mapping and an active billing-account row lock held to commit. The shared quota counts all statement/current/entry revisions, up to 1,000 per owner; correction history consumes that quota and exact retained retries do not.

Both parent and child admission check owner/context again after blocking waits, including the account-row wait. These checks cover direct internal runtime access when `owners.is_active` changes. Session revocation is a separate authentication boundary; this increment does not claim a globally serialized deactivation-versus-commit contract. Archival/remapping that commits before admission rejects stale writes; evidence admitted first can remain historical after a later change. Private service errors sanitize SQL failures.

## Recovery and migration

Recovery format **19** targets migration **0023**, with **50 application tables**, **46 durable exports** and the same four omitted session/admission/live-connector tables. The full manifest adds the parent entry discriminator and every one of the child's 15 stored columns. Mixed statement/current/entry histories and source mappings restore together under their structural constraints. Recovery remains bounded by the existing 4 MB and 1,000-rows-per-table limits. Formats 1–18 require their matching repository/schema for restoration followed by forward migration; this decoder does not silently reinterpret them.

Upgrade preserves populated statement/current histories and their defaults. Any populated credit evidence blocks downgrade; an empty downgrade restores the exact prior two-kind guard, constraints and grants without cascading deletion. Injected migration failures must leave the prior revision and structures intact. The recovery tests also require malformed/missing children, mixed ownership, wrong binding and partial original-value groups to roll back the entire restore, with old sessions still denied.

## Verification status

Focused Python and SQL acceptance cases cover exact retries and corrections, role/treatment and original-value distinctions, owner filtering, immutable grants, actual advisory/account lock waits, stale snapshots, two mixed-kind last-slot races, remapping/archival order, interrupted savepoints, schema preservation and complete two-owner encrypted restore. The focused local run passed **493 unit cases** and **378 PostgreSQL cases** (420.24 seconds), with strict typing on the service/recovery modules, lint and format checks on all eight changed Python files, and 1,059 local documentation links. Source/test review found no remaining actionable issue. Both disposable database projects and their credential contexts were removed, including nested recovery services. No hosted or provider-format compatibility is claimed; integrated verification is performed on the final combined tree.

The initial PostgreSQL run passed 100 cases before a new remap-test control exhausted the entry pool's two connections while its blocker and worker occupied them. The control was moved to the existing separate source runtime pool, retaining the exact lock observation, deadlines, runtime owner checks and outcome assertions. The complete 378-case rerun passed; no production guard, timeout or assertion was weakened.
