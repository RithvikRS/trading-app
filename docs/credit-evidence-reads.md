# Unselected credit financial evidence reads: Step 9B.7.2

Three protected read-only routes expose retained statement, current-report and entry evidence. They preserve exact native values and historical provenance; the newest stored interpretation is not a selected, fresh or paid account balance. No financial mutation, schema/grant/recovery change, acquisition or connected screen is introduced.

## Acceptance contract recorded before implementation

1. Query requires an owned account and explicit statement/current/entry kind. Return only the latest revision of each matching root, with bounded UUID pagination (25 default, 100 maximum, one validated sentinel). UUID order does not establish chronology, complete history or a frozen export.
2. History and exact-revision inspection bind the complete owner/account/kind/root tuple. Unknown, foreign, wrong-account, wrong-kind and missing revision share private 404. A known empty account/history cursor returns an empty page. Never replace a requested historical revision with the latest one.
3. Retain original plain decimal spelling and native currency, independent exact dates, source-local instant spelling/offset, negative-zero spelling, and missing reasons. Entry original cash absence, present-missing and zero remain distinct. Reconstruct typed CardStatementValues/CardCurrentValues/CardEntryValues contracts; private validation covers nested constructed/copied/cyclic response models through actual serialization.
4. Every evidence revision carries its frozen source/mapping revision and immutable account/kind, explicit predecessor and newest-revision flag. Later mapping changes or archival do not rewrite provenance. Account lifecycle is observed now; no freshness, coverage, paid/overdue, selected liability or net-worth field is inferred. Unsupported entry corrections remain visible and are neither withdrawal nor reversal.
5. Reuse the four metadata routes' active MFA/session/CSRF/origin/workspace-context boundary, credit-owner lock, READ ONLY/READ COMMITTED transactions and post-wait/end active-owner checks. Keep final session validation outside data catches and retain safe authentication status/cookie behavior. Projection failures exit the auth guard normally and return a fixed financial failure without invalidating a valid session.
6. SQL remains owner-bound and finite, with explicit allowlisted projections and complete typed-child/mapping joins. Validate the sentinel and all account/kind/root/revision bindings. No global counts, offsets, raw provider identifiers, raw documents, audit/acquisition timestamps, free text, issuer authentication claims or external calls appear. Explicit source-reported financial instants remain part of current-report values.
7. Unit and real PostgreSQL/HTTP tests exercise two owners, every kind, absent/missing/zero/native spelling, corrections, archived/remapped provenance, exact historical reads, limit/cursor bounds, private malformed projections, auth failures, actual lock waits and durable unchanged state. Existing metadata/value/persistence/recovery contracts remain covered.

## Route and response contract

All routes are POST JSON operations under `/api/v1/finance/credit`, with the existing [metadata-read protection](credit-identity-reads.md). `account_id` and the literal `kind` (`statement`, `current` or `entry`) are required everywhere.

| Route | Additional request fields | Result |
| --- | --- | --- |
| `/evidence/query` | Optional `after` UUID and `limit` | Latest stored revision of each matching root, ordered by UUID, with `next_after`. |
| `/evidence/history` | Root `id`; optional `before` revision and `limit` | Descending retained interpretations with `next_before`. |
| `/evidence/inspect` | Root `id` and exact `at_revision` | The requested retained interpretation; no substitution with a newer revision. |

Pages default to 25 records and cap at 100. A single validated SQL sentinel establishes a continuation. Each request observes its own state; UUID order is not chronology or a lifetime-history guarantee. A known account with no evidence returns an empty page. A history cursor can exhaust a known root, while an impossible empty initial history fails unavailable. Unknown, foreign, wrong-account, wrong-kind and missing-revision inspection share the existing private 404 behavior.

Every interpretation returns its internal root ID, kind, revision/predecessor, immutable source/account IDs, frozen mapping revision, observed account lifecycle and `is_latest_revision`. The last field means newest stored interpretation of this root. It does not mean selected, current in financial time, fresh, complete or paid. A source remap does not rebind old evidence; archived account evidence stays readable with its observed state.

## Exact financial evidence

Each kind has its own finite payload model. Statement evidence retains independent period start/end and statement/due dates and opening/closing liability, total due and minimum due. Current reports retain the source-local date and optional original offset-bearing instant, plus independent outstanding, unbilled, credit-limit and available-credit evidence. Entries retain explicit role/treatment, independent transaction/posting dates, billed INR and optional original INR/USD evidence. Unsupported interpretations remain visible retained evidence; no withdrawal, cancellation or reversal operation is inferred.

Each cash object contains only original decimal `source`, native `currency` and `missing_reason`. An absent original entry amount is JSON null; a present-but-missing object retains its currency and explicit reason. Zero, negative-zero spelling and original trailing decimal zeros are preserved. There are no JSON floating-point amounts, fabricated FX conversions or duplicate reformatted monetary values. The existing pure credit-card contracts validate signs, currencies, dates, source-local instants and pending/unsupported semantics.

## Read and privacy boundary

The same active MFA session, origin/CSRF/workspace-context checks and final session validator protect all seven credit read routes. The financial transaction remains READ ONLY at READ COMMITTED and uses the same credit owner advisory lock as writes, with active-owner/context checks after waiting and before completion. Account archival and administrative deactivation do not gain a global commit-ordering contract.

SQL uses fixed typed-child projections with exact owner/account/kind/root/revision filters and retained mapping joins. Missing or inconsistent projection fields fail privately; no raw row exception escapes into authentication failure handling. DTOs, including nested constructed/copied/cyclic instances, are checked before serialization with finite depth/page/response limits. Financial projection failures leave the authentication guard normally and preserve a valid session; final authentication failures retain their own status and cookie semantics. No financial writes, provider calls, card digits, issuer references, raw documents, audit timestamps, financial selections or connected card screens are added.

## Verification status

Focused checks passed 735 unit tests in 5.00 seconds, strict typing for four modules, lint/format for eight Python files and 1,104 documentation links. The unit and production sources remained unchanged after those checks. The 408-case PostgreSQL set covers 47 new HTTP/evidence cases, existing identity/financial/session reads, all three credit persistence kinds and encrypted recovery.

The first attempt passed 24 cases before a synthetic final-validator exception expected the wrong response. A reviewed test-only correction retained the registry's existing authentication-outage behavior and strengthened the real pre-SQL stale-context assertions; production guards did not change. The complete rerun passed 407 cases, then the unchanged recovery test failed during account-store transaction admission before export. Its original short log does not identify the underlying SQLAlchemy cause. A separate fresh recovery-only run passed unchanged in 40.79 seconds; no root-cause fix is claimed and the 408-case combined run is not represented as passing.

Targeted lint/format and the subsequent database runs cover the test-only correction. Both failed attempts and the successful diagnostic are retained. All owned disposable services/networks and temporary credential directories were removed, including nested recovery cleanup. Independent source/regression review found no remaining concrete defect; the final integrated all-five local gate must pass before merge. The current migration 0023 / format 19 / 50 application / 46 durable table inventory is unchanged.
