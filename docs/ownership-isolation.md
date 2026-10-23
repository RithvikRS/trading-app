# Step 3D: Ownership and database isolation

The database now separates each owner's display preferences from every other owner's records. This is an internal persistence boundary, exercised with synthetic identities. There is no HTTP owner-provisioning endpoint, workspace route, or connection from the prototype to this database. [Step 3E.1](authentication-foundation.md) adds internal Supabase verification and an administrative local provisioning command; [Step 3E.2](browser-sessions.md) adds opt-in browser authentication and the private security registry.

## Schema and controlled identity mapping

Revision `0002_workspace_ownership` follows the unchanged [PostgreSQL baseline](database-foundation.md). It adds three tables inside the private `app` schema:

| Table | Purpose and constraints | Runtime access |
| --- | --- | --- |
| `owners` | Explicit, nonzero internal UUID; active flag defaults to false; creation timestamp | Read only the current active owner; no creation, activation, update, or deletion |
| `owner_identities` | Unique, case-sensitive `(issuer, subject)` pair mapped to an existing owner; bounded nonempty strings and creation timestamp | No read/write grants or row policies; denied by default |
| `workspace_preferences` | One row per owner; constrained theme/currency, non-null masking, creation/update timestamps, owner foreign key | Read, insert allowed fields, update preference fields for the current active owner only |

All three tables have both `ENABLE ROW LEVEL SECURITY` and `FORCE ROW LEVEL SECURITY`. The migrator owns them; runtime owns none. The table owner is also subject to row policies for ordinary data access. A superuser still bypasses RLS and the schema owner can change policies; these remain trusted administrative identities. [PostgreSQL row security](https://www.postgresql.org/docs/17/ddl-rowsecurity.html).

Provisioning is deliberately absent from the normal application path. Disposable fixtures create synthetic owners as the local administrator. Step 3E.1 adds explicit administrative provisioning and a separate restricted identity-lookup role; ordinary login cannot provision owners. A matching email is not an identity mapping. Unknown identities must not automatically create owners, and no provider-managed authentication schema is changed here.

Issuer and subject values use exact `C` collation comparisons with a composite primary key; the same subject at a different issuer is a distinct identity. The maximum sizes are 512 and 256 UTF-8 bytes, respectively. Owner references use foreign keys with restricted deletion. Future relationships between owner-scoped domain records will also need ownership-consistent keys; those financial tables do not exist yet.

## Row policies and least privilege

`app.current_owner_id()` reads the transaction's `app.owner_id` setting. Missing, empty, malformed, unknown, and disabled contexts cannot expose owner data. Invalid UUID text produces no identity rather than a cast error. The helper is a stable, security-invoker function with a fixed `pg_catalog` search path; there are no security-definer functions in this migration.

The owners policy allows the runtime role to see only its active owner. The preferences policy uses both `USING` and `WITH CHECK` to require that same owner and an active owner record. A missing owner filter in a SQL query still cannot read or update another owner's rows. Cross-owner inserts/upserts fail, including attempts to reassign ownership. [Policy checks](https://www.postgresql.org/docs/17/sql-createpolicy.html).

Runtime receives no DELETE, TRUNCATE, ownership-update, timestamp-update, identity-management, or policy-management grants. Only the required context helper is executable directly. PostgreSQL sets preference timestamps, and an invoker trigger maintains `updated_at`. Default privileges remain closed for future objects. Tests temporarily expand specific grants inside a disposable cluster to prove that row policies still reject cross-owner reassignment and deletion independently of the normal ACLs.

The context setting is not an authentication mechanism. Code or credentials with arbitrary runtime SQL access can choose another valid owner context. The application therefore must verify identity on the server, use parameterized queries, and prevent arbitrary SQL execution. RLS is an additional boundary for correctly scoped application operations; it does not protect against a compromised application process or database administrator.

## Internal transaction interface

`trading_db.workspace.WorkspaceDatabase` accepts only the restricted runtime connection. Its `transaction()` method requires an already-resolved internal UUID, verifies the local server and runtime privileges, binds that UUID with parameterized `set_config(..., true)`, and checks that the owner is active before yielding a unit of work. Elevated role attributes, role memberships, schema/table ownership, and database/schema creation or temporary-table privileges are rejected. No identity is read from headers, request bodies, environment variables, or browser state.

The unit's public methods read or save validated preferences without an owner override or raw SQL interface. Owner identifiers come exclusively from the transaction scope. Preference payloads allow `light`/`dark`, `INR`/`USD`, and a strict boolean masking flag; new records default to masked amounts. Unexpected fields and coercions are rejected. No financial amounts are stored. Transactions commit on normal exit and roll back on exceptions, including cancellation. A unit cannot be used after its transaction ends.

Connections use UTC and `READ COMMITTED`. Owner status is checked at entry and by RLS on each statement; disabling an owner affects subsequent statements after that change commits. It does not retroactively undo a statement already authorized by its database snapshot. The original internal upsert remains for migration compatibility. [Step 3F.2](display-preferences.md) exposes only versioned compare-and-save operations through the authenticated API: stale writes return a conflict, saved account settings take precedence, and a short session guard orders application revocation against commit.

The interface is synchronous and currently used only by tests. Integrating it into HTTP request handling will require the appropriate execution/cancellation strategy; no asynchronous-driver or hosted-pooler behavior is claimed here.

## Connection reuse, rollback, and cancellation

Owner context is transaction-local and expires at commit or rollback. Runtime connections start with an empty context. On pool return, the reset handler first rolls back unfinished work, then clears any session-level owner setting in a separate committed cleanup operation. Cleanup cannot commit unfinished preference writes. If reset fails, the connection is invalidated and discarded with a fixed diagnostic instead of a raw driver payload. [Transaction-local settings](https://www.postgresql.org/docs/17/sql-set.html), [SQLAlchemy pool reset](https://docs.sqlalchemy.org/en/21/core/pooling.html#reset-on-return).

Real PostgreSQL checks prove that the same physical connection has no owner and sees no preferences after success, application/SQL failure, and cancellation. They also cover accidental session-level context, cancellation of an actual `pg_sleep` query, a cancelled Python task, loss of a connection, and concurrent owners on separate pool connections. Reconnection starts without identity, and retrying a unit requires a new explicit owner scope. The existing two-connection/no-overflow pool and statement/lock/idle limits remain in force.

## Migration, verification, and remaining work

Use the existing commands from the repository root:

```powershell
python scripts/database.py up
python scripts/database.py migrate
python scripts/database.py status
python scripts/checks.py all
```

The Step 3D revision is `0002_workspace_ownership`; [Step 3E.1](authentication-foundation.md) adds `0003_auth_identity_lookup`; [Step 3E.2](browser-sessions.md) adds `0004_browser_sessions`; [Step 3F.2](display-preferences.md) advances the current head to `0005_preference_revisions`. Migration creates no owner or preference rows in development. Fresh installs and upgrades from `0001_private_schema` are tested, including repeated upgrades that preserve data. A failed later revision rolls the complete transaction back to its starting revision, whether starting from an empty database, the baseline, or the ownership revision. Disposable downgrade/re-upgrade checks restore the schema; unexpected dependencies are not removed with `CASCADE`. Normal development recovery uses a forward migration. Downgrading this revision would remove its tables and is unavailable through the ordinary development command.

The existing **Database checks** CI job runs these tests in its own disposable PostgreSQL cluster, alongside the Python, frontend, and repository-security jobs. The original baseline tests remain explicitly pinned to revision `0001_private_schema`; ownership tests cover the new head. No production credentials or provider connections are used.

Local Windows verification on 23 October 2026: `python scripts/checks.py all` passed, including 15 verification-helper tests, 92 API/unit tests, 73 PostgreSQL tests, and 478 frontend tests. Ruff, strict mypy, frontend type checking/build, documentation links, workflow policy/actionlint, and repository secret scans passed. Python and npm audits reported no known vulnerabilities. Development upgraded to `0002_workspace_ownership`; all three new tables were verified empty. GitHub CI results are recorded separately in the corresponding PR.

Step 3E.1 implements internal password/MFA verification, restricted enrollment, and identity lookup. [Step 3E.2](browser-sessions.md) now implements browser login, revocable sessions, recovery, and security events. The frontend still uses fictional records, and no real financial data belongs in the application. Hosted Supabase TLS, grants, RLS behavior, pooler compatibility, backup restoration, and Oracle deployment have not been verified by these local tests.
