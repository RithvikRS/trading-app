# Oracle and Authelia migration

Review date: 10 November 2026. This implements the compatibility review and roadmap reconciliation for the [5 November decision](oracle-authelia-decisions.md). It does not implement an Oracle database adapter, OIDC login or hosted deployment.

## Current state and target

The reviewed application baseline is `1b5bad4d99529f2da2bf18718b222a180a219388` (PR #92). It has 25 PostgreSQL migrations through `0025_market_nav_occurrence`, recovery format 21, 51 application tables, 47 retained durable tables and four deliberately omitted live session/admission/connector tables. Existing local tests establish PostgreSQL and synthetic Supabase behavior only.

| Boundary | Implemented | Selected target |
| --- | --- | --- |
| Application | React/TypeScript/Vite and Python/FastAPI | Retain these components and same-origin API access |
| Database | Local PostgreSQL 17, Psycopg, SQLAlchemy and Alembic | Oracle Autonomous Database; Always Free only if the selected service satisfies the controls below |
| Identity | Server-side Supabase password/TOTP integration | Native Authelia OIDC authorization code flow with MFA and PKCE |
| Sessions | Opaque app cookie, encrypted server state, revocation and workspace-context checks | Preserve app authority; introduce deliberately versioned OIDC session state |
| Hosting | Restricted loopback Compose rehearsal; packaged sign-in unavailable | Separate trading Swarm release on Ampere A1, Caddy ingress on AMD node 1 |
| Recovery | Encrypted synthetic PostgreSQL export/restore rehearsal | Tested Oracle-consistent export/restore plus independent statement, configuration and key recovery |

Local PostgreSQL remains usable while its replacement is developed. Keep applied migrations and old recovery decoders intact. Do not rename the PostgreSQL schema history into an Oracle baseline or reinterpret existing sessions as OIDC sessions. Before any populated-environment transition, inspect actual data and identities and verify backups; synthetic fixtures are not an environment inventory.

## Shared infrastructure prerequisites

Read-only review of the separate portfolio repository at `52631d208b962f7208273cee35f9ce0f7549761b` found the following documented state. The reviewed paths are `deploy/STORAGE.md`, `deploy/MONITORING.md`, `deploy/BACKUPS.md`, `deploy/FAMILY-SERVICES.md`, `deploy/SERVICES-ROADMAP.md` and the public Authelia configuration. This is repository evidence, not a new live infrastructure inspection. An existing uncommitted backup-document addition was not changed or imported.

| Area | Repository evidence | Still required for trading |
| --- | --- | --- |
| Worker storage | Exact-node worker placement and backup guards; dedicated Ampere application storage | Explicit statement/key paths, permissions, single-writer placement and coordinated recovery coverage |
| Monitoring | Kuma documented on AMD node 2 with protected access and bounded resources | Independent external outage alerts, delivery/recovery rehearsal and trading-specific safe health checks |
| Identity | Dedicated clients, group restrictions and two-factor policies for other services | Dedicated trading client; actual assurance/freshness, offboarding and two-user isolation evidence |
| Backups | Coordinated manager/worker kits and architecture-specific images | Independent encrypted copies and a complete restore exercise; checksums alone do not demonstrate recoverability |
| Releases | Trading belongs in its own repository and lifecycle | Own stack/image, hostname, migration executor and compatible release/recovery runbook |

Shared backup documentation explicitly says the local archives are ACL-protected but not password-encrypted. Do not describe them as the financial application's encrypted off-tenancy recovery solution. No private backup files or live credentials were inspected.

Compatibility research can proceed now. The shared infrastructure, recovery, monitoring and identity prerequisites remain dependency gates before application migration implementation under the handoff's sequencing. A later source or runtime receipt can close a specific gate; another application's deployment does not establish trading readiness.

## Oracle compatibility inventory

| Surface and current source | Porting requirement and proof |
| --- | --- |
| [Connection and pool guards](../backend/trading_db/connections.py), [bootstrap](../backend/trading_db/bootstrap.py) | Add a separate Oracle target/driver configuration. Keep the existing literal-loopback disposable PostgreSQL guards. Prove TLS certificate/hostname rejection, bounded pools, disconnection and failed-cleanup invalidation. |
| [Owner transactions](../backend/trading_db/workspace.py), [ownership migration](../backend/migrations/versions/0002_workspace_ownership.py) | Replace forced PostgreSQL RLS and transaction-local settings with a reviewed Oracle policy/application-context design. Test direct restricted-role SQL, missing/malformed/inactive owner denial, cross-owner denial and cleanup after every exit path. |
| [Migration executor](../backend/trading_db/migrate.py), [25 applied revisions](../backend/migrations/versions) | Oracle DDL has implicit commit boundaries. Introduce a separate baseline, interrupted-migration detection/journal, bounded execution and recovery strategy; do not promise all-DDL rollback. |
| [Accounts](../backend/trading_db/accounts.py), [sessions](../backend/trading_db/sessions.py), [bank mappings](../backend/trading_db/bank_mappings.py) | Replace advisory locks and `FOR SHARE` deliberately. Prove lock order, post-wait owner/target checks, bounded cancellation, exact historical replay and concurrent duplicate prevention. |
| [Financial migrations](../backend/migrations/versions/0006_accounts_sources.py) through [reconciliation](../backend/migrations/versions/0017_reconciled_completion.py) | Inventory PL/pgSQL, deferred constraint triggers, function-backed CHECKs and JSONB canonicalization/hashing. Preserve each invariant with supported Oracle constraints/packages and tests; deferrable keys alone do not replace every deferred trigger. |
| [Exact financial contracts](../backend/trading_api/finance.py) | Preserve bounded Decimal semantics, original source spelling, native currencies, explicit unknowns and rejection of excess scale. Test binds, fetches, SQL expressions and intermediate arithmetic; no binary-float path. |
| UUID, binary, timestamps, boolean, text and raw SQL throughout persistence | Choose explicit mappings for UUID/bytea/timestamptz/boolean, casts, regex, conflict handling, pagination and case-sensitive identity comparisons. Test UTC microseconds, source-local instants, UTF-8 byte bounds, empty versus null and exact round trips. |
| [Recovery](../backend/trading_db/recovery.py) | Retain the old encrypted format and introduce explicit engine/schema provenance. Replace catalog/RLS inspection and snapshot assumptions with Oracle-consistent reads and staged restore validation; invalidate live sessions and require connector reconnection. |

Candidate database isolation is a trusted Oracle application context with Virtual Private Database policies. The context setter must have a defined authorization boundary; a public procedure accepting any owner ID is not proof of authenticated ownership. Runtime must not own protected objects, manage policies or possess `EXEMPT ACCESS POLICY`. Separate bootstrap, migration, runtime and identity responsibilities. Connection rollback alone must not be assumed to clear session context; test clearing on checkout/return and discard connections after failed cleanup. Oracle documents VPD and trusted contexts, and lists VPD for local Database Free; exact Autonomous service privileges and behavior still require a probe. [VPD](https://docs.oracle.com/en/database/oracle/oracle-database/21/dbseg/using-oracle-vpd-to-control-data-access.html), [feature matrix](https://docs.oracle.com/en/database/oracle/oracle-database/26/dblic/Licensing-Information.html).

Oracle's implicit DDL commits and CHECK restrictions require semantic changes. Oracle supports deferrable constraints, but CHECK expressions cannot call user-defined functions. Preserve database-enforced ownership and financial invariants; optional application query filters are not an acceptable substitute. [Transactions](https://docs.oracle.com/en/database/oracle/oracle-database/19/cncpt/transactions.html), [constraints](https://docs.oracle.com/en/database/oracle/oracle-database/26/sqlrf/constraint.html).

The current individual financial bound is 18 integer plus 12 fractional digits, within Oracle NUMBER's 38-digit precision. That does not establish exact handling of every expression or authorize silent scale rounding. Preserve validated decimal text separately from numeric projections, distinguish absent/missing/zero, and check Decimal results for the actual raw-SQL query shapes. [SQLAlchemy precision behavior](https://docs.sqlalchemy.org/en/21/dialects/oracle.html#precision-numerics), [driver numeric retrieval](https://python-oracledb.readthedocs.io/en/stable/user_guide/sql_execution.html#fetching-numbers).

### Environment and service decisions

The driver candidate is a stable `python-oracledb` Thin release through SQLAlchemy's `oracle+oracledb` dialect. Thin avoids Oracle Client libraries. No dependency is selected or installed in this increment. Verify a locked, binary-only install against the repository's Python 3.14.9 constraint and Linux ARM64; preserve `uv no-build=true`. Documentation support is not wheel-installation or TLS evidence. [Driver installation](https://python-oracledb.readthedocs.io/en/stable/user_guide/installation.html).

Use an isolated real Oracle environment for local integration checks, with a pinned official image/version/digest, synthetic users and disposable schemas. Verify host/CPU/resource requirements before starting it. Keep production credentials out of local checks and CI. Local Oracle Free establishes engine behavior for its tested version, not Autonomous grants or network behavior; separately prove those against a dedicated non-production service. [Local Free requirements](https://docs.oracle.com/en/database/oracle/oracle-database/26/xeinl/requirements.html).

The current Always Free documentation describes 20 GB storage, 30 simultaneous database sessions, no private endpoint, and restricted backup/restore facilities. Inactivity can stop and eventually reclaim a database. Choose the actual engine version, region, workload, access-list/TLS mode and total connection budget before provisioning. Independent encrypted exports and off-tenancy recovery are required; do not promise private-VCN-only access or managed point-in-time recovery on this tier. No paid upgrade is implied. [Always Free restrictions](https://docs.oracle.com/en-us/iaas/autonomous-database-serverless/doc/autonomous-always-free.html).

## Identity and session contract

The existing [identity database key](../backend/migrations/versions/0002_workspace_ownership.py) already uses exact `(issuer, subject)` text. Preserve internal owner UUIDs and financial ownership. Provision each verified Authelia identity explicitly; never link through email, display name, group membership or proxy headers. Existing infrastructure users do not receive trading access automatically.

The current [auth models](../backend/trading_auth/models.py), [configuration](../backend/trading_auth/config.py), [browser service](../backend/trading_auth/browser.py), [sealed session models](../backend/trading_auth/session_models.py) and [enrollment](../backend/trading_db/enrollment.py) contain Supabase-specific issuer, UUID subject/provider-session, factor and `aal2` assumptions. Introduce provider-neutral verified identity and versioned session contracts; do not manufacture those Supabase fields from OIDC claims.

The OIDC flow must meet these requirements:

- Dedicated confidential client, exact HTTPS callback and fixed issuer/metadata/token/JWKS destinations. Use a maintained OIDC implementation after checking the pinned Python/HTTP stack, with authorization code and S256 PKCE; do not add implicit or password grants.
- Short-lived server-side state, nonce and PKCE custody, atomically consumed callback state, durable admission limits and browser-bound correlation. Permit only the exact callback method/path and bounded parameter shape through the existing [authentication boundary](../backend/trading_api/authentication.py). Keep ordinary CSRF and origin controls intact.
- Validate signature, issuer, audience/authorized party, opaque subject, nonce, expiry and required assurance. Reject duplicate/malformed callback fields, replay, missing MFA and unknown owners. Keep a fixed return destination and remove callback parameters immediately; sanitize callback logs.
- Main sessions remain opaque, Secure, HttpOnly and Strict. A separate short-lived Lax correlation cookie may support the selected cross-site GET callback. Provider tokens and identity credentials never enter browser persistence. Password/MFA management moves to Authelia; the protected shell retains masking, session controls and clearing on context changes.
- Preserve app-controlled idle/absolute expiry, local revocation, final authorization before commit and cancellation handling. Refresh, if needed, uses encrypted server custody and serialization; it does not reset authentication freshness or justify blind retry after an uncertain exchange.

A dedicated `two_factor` client policy is necessary but not sufficient application evidence. Verify the installed Authelia release's signed `amr` and authentication-time behavior, including an existing SSO session and fresh authentication for sensitive operations. Missing/unsupported assurance must fail closed. Do not translate `aal2` into a claim Authelia never issued. [Client policy](https://www.authelia.com/configuration/identity-providers/openid-connect/clients/#authorization_policy), [AMR](https://www.authelia.com/reference/guides/authentication-method-references/), [ID-token validation](https://openid.net/specs/openid-connect-core-1_0.html#IDTokenValidation).

Offboarding needs an explicit app operation: disable the internal owner/identity and revoke app sessions. Authelia's support chart currently lists token introspection/revocation but not RP/front-channel/back-channel logout or session management. Client policy is evaluated at authorization. Neither an IdP logout, a successful refresh nor token introspection alone proves that a disabled user or changed group has lost an already-issued app session. Define and test the provider revalidation and maximum stale-access contract against the selected release before activation; do not silently remove existing upstream-access checks. [Supported protocols](https://www.authelia.com/integration/openid-connect/introduction/#support-chart), [Authelia token behavior](https://www.authelia.com/integration/openid-connect/frequently-asked-questions/#why-isnt-the-access-token-a-json-web-token).

Recovery must independently restore the IdP, app key material and explicit owner mappings. Invalidate pre-transition sessions and require fresh MFA after restore. Preserving an old identity mapping for audit does not keep that old login provider enabled. The exact migration/cutover inventory remains unperformed.

## Implementation sequence

These increments precede new database-dependent financial features. Each has its own focused PR and final integrated local verification. The current [PR standard](pull-requests.md) remains in force; GitHub Actions stays manual. Do not count the earlier estimate of remaining financial features as including this new migration work.

| Increment | Deliverable | Exit evidence |
| --- | --- | --- |
| OA1: Compatibility and design | This inventory, current/target documentation, shared prerequisite matrix; then resolve exact service/version, local environment, policy privileges, OIDC client/library, offboarding and recovery choices | Inventory delivered; environment/capability decisions and shared runtime evidence still open. No compatibility acceptance claimed. |
| OA2: Oracle foundation | Separate real-Oracle runner and baseline, restricted roles, trusted owner-context layer, pool cleanup and migration journal | Two synthetic owners; direct-SQL denial, no-context denial, success/error/cancel/reuse cleanup, interrupted DDL recovery, exact values and verified connectivity. Hosted service-specific probes remain separately identified. |
| OA3: Authelia integration | Synthetic protocol integration, closed enrollment, MFA assurance and app sessions, then a pinned non-production Authelia rehearsal | Forged/replayed callbacks, unsupported assurance, unknown owner, outage, key rotation, disable/group changes, refresh/revoke races and recovery fail closed. No existing-session resurrection. |
| OA4: Protected vertical slice | One authenticated preference/account flow through Oracle and the protected frontend | Two-user end-to-end isolation, revision conflicts, stale workspace context, masking and local revoke-all; exact source values remain unchanged. |
| OA5: Financial domain and recovery port | Accounts/instruments, source evidence/imports, events/lots, snapshots/markets, completion, credit evidence and existing reads, split into reviewable increments | Real Oracle precision, constraints, historical replay, concurrency and ownership regressions; complete encrypted two-owner restore with exact retained evidence and omitted live credentials. |
| OA6: Hosted synthetic staging | ARM image and separate Swarm stack, Caddy/callback rules, migration identity, resource bounds and safe health/freshness signals | Prerequisites satisfied; synthetic-only connectivity/login, restart/outage, direct-access denial, monitored restore and key/file recovery evidence. |
| OA7: Production readiness | Actual data/identity inventory, compatible migration/cutover and rollback runbook, backup schedule and operational limits | Staged restore/access tests and explicit cutover record; no real provider acquisition enabled by hosting alone. |

The selected Oracle and Authelia releases/configurations must be pinned before their runtime acceptance. Do not weaken current checks or point the local tools at a hosted target. Code/configuration/schema changes require all five existing local groups plus the new Oracle/OIDC checks appropriate to the increment; adjust the verification runner in a separately reviewed change once those real environments exist.

## Saved financial work

Three unmerged increments were saved before this architecture change. Their primary backup manifests and all 52 feature-file hashes were verified on 10 November; they are preserved for adaptation, not discarded or declared complete.

| Increment | Saved state | Re-entry requirement |
| --- | --- | --- |
| 8B.3 bank account archival | Source and focused backend/database results retained; frontend/build/browser and final integrated gate incomplete | Review final fixture correction, adapt the persistence/session boundaries and complete runtime acceptance on the selected foundation |
| 5F.3.1 NAV growth mappings | Source, focused Python/database results and static frontend check retained; frontend/browser acceptance incomplete | Preserve mapping/replay semantics and refresh integration against the new foundation |
| 9B.8.3 HDFC billing-account setup | Source and bounded unit/static checks retained; database/frontend/browser acceptance incomplete | Preserve atomic creation receipts and exact retries; reconcile its unmerged PostgreSQL `0026` candidate with the deliberate Oracle baseline |

The manual NAV preview remains a reviewed design only. Keep its upload/cancellation/privacy contracts, but re-evaluate database/session dependencies before implementation. Historical test results apply only to their recorded sources and environments. Missing old worktree directories can be reconstructed from the verified backups; do not treat a stale worktree attachment as source authority.

## Evidence and outstanding work

This increment performs source inventory, official-documentation review, shared-repository prerequisite review and backup integrity checks. It changes documentation only. No Oracle instance/image/driver, dedicated Authelia client, live IdP operation, provider acquisition, production migration or hosted release was performed. Repository verification is recorded with the resulting PR; no Oracle or Authelia runtime result is implied.
