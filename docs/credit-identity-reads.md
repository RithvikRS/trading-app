# Protected credit identity and provenance reads: Step 9B.7.1

This increment exposes only owned HDFC/INR billing identities and opaque credit source/mapping history through four protected read-only JSON routes. Statement/current/entry financial evidence, mutations, connected screens and provider imports are separate work. No table, column, grant or recovery-format change is introduced.

## Acceptance contract recorded before implementation

1. Account query/inspection and source query/mapping history retain only allowlisted owned identities, explicit mapping revisions and current lifecycle. Never-mapped, unlinked, mapped and archived-target states remain distinct; archived links stay readable without active-only resolution.
2. Strict private request/response contracts reject wrong types, unknown fields, malformed/noncanonical/zero UUIDs, invalid revisions, label digits and counterfeit model_construct/model_copy instances. Invalid response payloads must not escape through serialization, logs, repr or warnings.
3. Public pages stay within 1–100 rows (default 25), with one bounded 101-row SQL sentinel; UUID order is not chronology. History uses strictly descending revisions and exact source binding. Unknown/foreign parents share safe 404; a known never-mapped source returns an empty history page.
4. Existing active MFA session, CSRF, exact-origin, workspace-context, JSON/body and HTTP privacy boundaries protect all four POST routes. Revoked/expired/idle/non-active sessions and stale contexts must fail before credit SQL. Active read policy adds no interactive fresh-MFA requirement.
5. The restricted financial transaction is READ ONLY and uses the credit owner advisory lock, with active-owner/context checks after waiting and before response completion. Actual observed lock waits exercise deactivation, mapping ordering and owner-B independence; direct archival remains an observed lifecycle state, not immutable history or a global commit-order guarantee.
6. Final session validation precedes releasing serialized data. Projection/database/response-size failures become the fixed financial-data failure after a normal auth-guard exit, without revoking a valid replacement session or yielding partial/empty success.
7. Missing filters cannot bypass forced owner RLS, injected writes fail in READ ONLY transactions, and pooled owner/read-only state resets on every exit. Before/after durable evidence remains unchanged; normal authentication registry bookkeeping is separate.
8. No owner identifiers, financial values, card digits, external references, raw documents, arbitrary metadata, timestamps, acquisition or financial-selection claims appear. Existing financial/session tests and the complete integrated local gate remain prerequisites for integration.

## Protected read contract

The following POST routes share the existing authenticated financial browser boundary. Account and source queries accept `after` and `limit`; inspection accepts `id`; mapping history accepts the source `id`, `before` revision and `limit`.

| Route | Returned information |
| --- | --- |
| `/api/v1/finance/credit/accounts/query` | Owned billing identities, safe nicknames, identity revision and observed active/archived state. |
| `/api/v1/finance/credit/accounts/inspect` | One owned billing identity with the same minimal fields. |
| `/api/v1/finance/credit/sources/query` | Opaque HDFC credit source handles and their latest mapping revision/target, including archived targets. |
| `/api/v1/finance/credit/sources/mappings/history` | Retained target, reason and predecessor for each mapping revision, with latest-revision status and the target account lifecycle observed by this query. |

A source with no mapping has no mapping revision. An explicitly unlinked source retains its latest revision with a null target. Mapping history preserves former targets, including archived accounts; current lifecycle does not rewrite historical mapping identity. Unknown, foreign-owner and asset-account identities share the same private 404 response. A known never-mapped source has an empty history page.

Pages default to 25 rows and accept at most 100. SQL fetches at most one additional row to establish a continuation and validates that row too. UUID keyset order is not date order or a lifetime-history claim. Mapping revisions are strictly descending and bound to the requested source; no totals or automatic traversal are exposed.

## Security and failure behavior

The routes require the existing active MFA browser session, CSRF token, exact origin and current workspace context. They preserve the existing active-read policy without an extra interactive freshness challenge. The restricted database transaction is `READ ONLY` at `READ COMMITTED`, takes the same credit owner advisory lock used by credit writes, and checks active owner/context after waiting and before completion. Archival may happen outside that lock; lifecycle is observed per query, not represented as immutable mapping history or a global deactivation/commit-order guarantee.

Declared response fields are recursively extracted without serializing unchecked model instances, then validated again before JSON serialization. Extra, missing, oversized, cyclic and constructed/copied invalid model fields fail privately. Database, projection and response-cap failures leave the authentication guard normally, preserve a valid session and return `financial_data_unavailable`; they do not yield a partial response. Final authentication validation retains its own denial, retry and availability semantics. The response is serialized before that final validation and released only after the protected transactions finish.

No financial values or evidence records are queried by these routes. There are no writes, card digits, external identifiers, timestamps, provider requests or connected credit-card screens. The existing migration 0023 / recovery format 19 contract is unchanged: 50 application tables, 46 durable exports and four live security omissions. See the [identity registry](credit-account-identity.md), [source mappings](credit-source-mappings.md) and [entry evidence](credit-entry-evidence.md) for their separate storage boundaries.

## Verification status

Focused verification passed: 337 unit tests; strict typing for four modules; lint and format checks for seven Python files; and 1,071 local documentation links. The isolated PostgreSQL set passed all 189 tests in 319.21 seconds, covering these routes, existing financial reads/preferences, credit identities/source mappings and the complete encrypted recovery round trip. No source or fixture correction was needed during this run. The owned disposable database, network and test credential directories were removed. Independent source and regression review found no remaining issues. The complete integrated local gate remains required before integration.
