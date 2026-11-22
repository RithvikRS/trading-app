# Local Oracle ownership baseline

OA2.2 adds a disposable local ownership and preference baseline beside the active PostgreSQL implementation. The HTTP application, browser authentication, sessions and existing PostgreSQL migrations continue to use their current paths. These modules accept only the owned local verifier's fixed loopback target; they are not a hosted database configuration surface.

The earlier ownership candidate passed 212 pure tests, Ruff, strict typing and the real Oracle acceptance run. That successful run completed the retained smoke, all 44 before/after-DDL interruption and reconciliation points, exact ownership and identity checks, preferences, connection custody, concurrency, final schema validation and client closure. Its receipt matches that historical source digest, and the owned container, network and credential files were removed. Three earlier failed attempts remain preserved separately with their source versions and cleanup evidence. The subsequent condition-projection correction passed fresh pure and actual-engine verification described below; its new receipt is bound to the corrected source, separately from that historical result.

## Identities and grants

The owned bootstrap administrator creates three fixed identities. `TRADING_MIGRATOR` owns the schema, has four direct system privileges (`CREATE SESSION`, `CREATE TABLE`, `CREATE PROCEDURE`, `CREATE TRIGGER`), four explicitly granted SYS packages, and an 8 MiB quota. The other identities have only `CREATE SESSION`, zero quota, no owned objects and no granted roles. The bootstrap removes the implicit PUBLIC permission to inherit each new user's privileges.

`TRADING_RUNTIME` can read the installation marker and protected owner/preferences tables, execute the owner-context package, insert the four preference input columns, and update its three display values. It cannot modify owners, read identity mappings, write revisions/timestamps directly, delete preferences, administer policies or create objects. `TRADING_AUTH` can read the marker and execute the exact identity lookup package. It receives no direct identity-table or owner-table access. Neither client receives `EXEMPT ACCESS POLICY`, `CONNECT`, `RESOURCE`, schema ownership or a general-purpose SQL package.

Runtime and authentication logins remain locked during installation. Before unlocking them, the bootstrap rechecks the run marker and context binding, all schema objects, source definitions, constraints, policies, the checksum journal, direct privileges, quotas and grants. Every native connection checkout and return also verifies the session/current/schema identity, expected system/direct/effective application grants, absent roles, client object ownership and the ready marker. Privileged host/database administrators remain trusted; this is not isolation from a compromised administrator or runtime database credential.

## Ownership and exact values

The three domain tables are `owners`, `owner_identities` and `workspace_preferences`. Owner IDs use exactly 16 nonzero RAW bytes. Owners default to inactive. Identity keys preserve exact bounded UTF-8 bytes: issuer up to 512 bytes and subject up to 256 bytes. No case folding, slash normalization or Unicode normalization joins distinct identities. The Python boundary rejects empty strings, leading/trailing whitespace and control characters; the lookup package accepts only the restricted authentication session. Identity bindings are immutable. Resolving an identity is a persistence operation, not provider-token validation.

The context package clears the previous owner before validating a canonical nonzero UUID, checks that the owner is active, and clears context after any failed setter. Caller checks use `SESSION_USER`; a client identifier does not confer ownership. Session-local VPD policies scope all four DML operations and enforce insert/update predicates. The owners policy avoids a recursive lookup; the preferences policy additionally checks active ownership.

The API must independently verify the owner before choosing a context. A holder of the runtime credential can invoke its permitted context setter for another active owner; the design does not claim protection after that credential is compromised. Final authenticated session authorization around a preference commit remains later integration work.

Preferences reuse the existing strict display models: light theme, INR and masked amounts by default. Missing preferences return revision zero without inserting a row. Stored revisions use unconstrained `NUMBER` with an integral range check from 1 through 9007199254740991; declaring `NUMBER(p,0)` would permit rounding before the constraint. A trigger owns revision and timestamp changes. An update locks the owner with a five-second bounded wait, rechecks activity after waiting, compares the exact revision, and saves while holding that lock until commit. Deactivation must acquire the same owner lock. A stale or terminal revision returns a conflict without a write.

Read-only transactions intentionally retain Oracle's initial transaction snapshot. A deactivation committed afterward is not guaranteed to become visible inside that already-open read-only transaction. This is a display-read snapshot boundary, not immediate authenticated-session revocation; final application authorization remains later integration work.

## Pool custody

There is one homogeneous native pool per client role, bounded to two connections and a five-second wait. There is no SQLAlchemy pool layered above it. The target is fixed to IPv4 loopback and `FREEPDB1`; connection retries are disabled, network connection and database calls are bounded, the driver must be Thin, and the fresh isolated process uses the verifier's empty guarded configuration directory. Queries request exact decimal fetches locally without changing process-wide driver defaults.

Checkout and return roll back outstanding work, verify identity/readiness, clear and verify owner context, clear client identifiers and set/verify UTC. A connection that fails cleanup or encounters a driver error is dropped. A failed drop poisons the pool; admission is checked again after a queued acquire finishes. Closing a pool with an active lease is refused. Starting a close permanently stops admission, but the pool is marked closed only after native close succeeds. One bounded close retry is retained after failure; further failure stays visible and requires the owned verifier's final resource cleanup. Migrator cleanup attempts close even if rollback fails and emits only fixed diagnostics. A closed transaction cannot reopen or move to another thread. Failed or uncertain commits are never retried.

Custody is synchronous in this increment. Tests cover ordinary exceptions and `BaseException` cancellation-like exits after control returns to Python. An eventual asynchronous request/worker integration must retain custody until its worker has actually finished; cancelling the request alone must not return an executing connection to the pool. That integration is not implemented here.

## Committing DDL and recovery

Initial role/control-plane bootstrap is one-shot. A failure there leaves clients unavailable and requires rebuilding the owned disposable instance; it is not a generally rerunnable hosted bootstrap. The application DDL sequence is fixed and checksum-bound. A migration-only numeric `DBMS_LOCK` has an exclusive five-second wait, survives commits, and is explicitly released with its result checked.

Each DDL or committing policy call has a committed `STARTED` journal record before execution. Exact metadata is checked before recording `APPLIED`. An interruption leaves `STARTED` and blocks ordinary installation. Explicit reconciliation can accept an exact expected post-state, or record an absent expected pre-state as `ABANDONED` before a new bounded attempt. Three attempts are allowed per step; old records remain. Partial objects, checksum drift, altered grants/policies/source, history gaps and unexpected objects fail closed. There is no general downgrade, object-dropping recovery or claim that rolling back reverses Oracle DDL.

Constraint conditions use a closed raw-text profile before semantic comparison: exact nonempty ASCII strings of at most 512 characters, checked before stripping or normalization. The original 40 expected baseline predicates are ASCII and at most 109 characters. The cap intentionally rejects excessive formatting even when normalization would otherwise compare equal. All original SQL, checksums, journal keys and privileges remain unchanged.

Oracle documents `SEARCH_CONDITION_VC` as a 4,000-capacity projection that can truncate a longer condition. Normalization alone could accept an expected prefix padded with whitespace while a weaker suffix falls outside that projection. The 512-character ASCII profile conservatively refuses that boundary; it is not a general completeness guarantee for arbitrary or untrusted row producers. This correction retains the bounded VC projection and does not add unbounded LONG acquisition. Fresh acceptance on the pinned local engine confirmed ordinary metadata formatting and rejection of the deliberately truncated condition. [Oracle constraint dictionary](https://docs.oracle.com/en/database/oracle/oracle-database/26/refrn/ALL_CONSTRAINTS.html).

## Local acceptance runner

From the `backend` directory, the local command is:

```powershell
.\.venv\Scripts\python.exe -m trading_oracle.baseline
```

It retains the existing OA2.1 smoke and exact `LocalRun` custody/cleanup, then starts one fresh isolated acceptance process. That child receives only the bounded run ID/port descriptor, independently checks the local Docker context and owned manifest, and generates role credentials only in memory. No role credentials are transported through arguments, environment variables or a file. The parent keeps the verifier lock and resource custody until the child finishes or its 900-second deadline expires.

A private `baseline-result.json` receipt records only fixed stages, their completed prefix, an optional numeric Oracle error code and the exact source-bundle digest. The parent checks the digest before and after execution and validates the bounded receipt schema. Raw SQL, driver messages and credentials are excluded. Existing failed manifests and receipts remain available; cleanup removes only the exact owned resources and known local credential files.

The unlock check uses exact scalar metadata predicates, avoiding dependence on SQLPlus column widths. Metadata, source, policy, grant, marker and journal checks all remain mandatory before either client identity is unlocked.

Oracle documents 41900 as a missing object privilege. Deliberate privilege-denial checks recognize that code alongside their existing expected errors, while positive operations, VPD rejection and owner-context rejection remain strict. No extra privileges were granted to satisfy these checks. [Oracle error reference](https://docs.oracle.com/en/error-help/db/ora-41900/)

Oracle also documents code 54 for a lock held by another session, including wait expiry. The deliberate `WAIT 5` expiry test accepts 54 or 30006 and proved 4–12 seconds of elapsed wait with an unchanged preference revision. An immediate `NOWAIT` failure, unrelated error, successful write or timeout on a positive operation does not satisfy that test. No production timeout, SQL, grants or application behavior changed. [Oracle lock error reference](https://docs.oracle.com/en/error-help/db/ora-00054/index.html)

The earlier candidate's real suite passed:

- Two-owner direct-SQL isolation, malformed/missing/inactive/unknown contexts, failed-setter clearing, fake client identifiers, forbidden privileges and metadata drift denial.
- Exact identity lookup, absent nonpersistent preferences, correct revision transitions and terminal conflicts.
- Same-physical-connection reuse after success, errors and cancellation-like exits, plus actual cleanup rejection and connection replacement after privilege drift. Failure of the native drop operation itself, subsequent pool poisoning and queued-acquire denial are covered by injected pure tests rather than forced failures of the real driver.
- Concurrent revision winners, actual server `WAIT 5` expiry, both owner-deactivation orderings and the documented read-only snapshot boundary. The expiry acceptance case temporarily uses a ten-second outer driver deadline to observe Oracle's five-second timeout independently; production checkout/return still uses the fixed five-second call timeout.
- Failure before and after every committing install step, explicit reconciliation, preserved journal history and no premature client unlock.
- Cleanup of the exact owned container/network and local verifier credentials after every attempt.

The new condition-projection case runs within the existing migration stage, before seed or client unlock. It first validates the ordinary schema, temporarily replaces only the fixed synthetic owners check with a padded weaker condition, requires an actual 4,000-character projection that would pass the old normalize-only comparison, and requires the corrected table/schema checks to deny it. A synthetic invalid owner value distinguishes the weakened check from the ordinary positive control. The case rolls back that row and restores the exact original constraint in `finally`; failed reproduction or restoration fails the stage and leaves disposal to the owned verifier. It adds no stage or receipt field: the changed source digest identifies this expanded migration acceptance. The corrected real-engine run passed all twelve stages, including this projection case and the original 44 interruption/reconciliation points. Its source-bound receipt confirms the expanded migration stage completed before unlock; the owned container, network and verifier credentials were cleaned.

The corrected source passes 398 focused pure tests (186 new condition and acceptance-flow regressions plus the original 212 cases), Ruff checks and formatting for all three Python files, and strict typing for the two production modules. The tests cover exact-cap positive controls, over-cap and padded-prefix rejection before normalization, counterfactual acceptance when the raw guard is removed, and restoration after projection, creation or restoration failure. These pure results complement the separately completed real-engine acceptance; the integrated repository gate remains required.

Local acceptance does not establish hosted Autonomous compatibility. Hosted privileges, authentication wiring, migration of existing financial data, backups and production cutover remain separate work.

References: [Oracle GRANT](https://docs.oracle.com/en/database/oracle/oracle-database/26/sqlrf/GRANT.html), [application contexts](https://docs.oracle.com/en/database/oracle/oracle-database/26/sqlrf/CREATE-CONTEXT.html), [DBMS_RLS](https://docs.oracle.com/en/database/oracle/oracle-database/26/arpls/DBMS_RLS.html), [DBMS_LOCK](https://docs.oracle.com/en/database/oracle/oracle-database/26/arpls/DBMS_LOCK.html), [native connection pools](https://python-oracledb.readthedocs.io/en/stable/api_manual/connection_pool.html).
