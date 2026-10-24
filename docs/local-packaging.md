# Local packaging and recovery rehearsal

Step 3G adds a digest-pinned Python/static frontend image, a restricted HTTPS gateway, measured local resource limits, and an encrypted synthetic restore exercise. These run through the same verification commands locally and in CI. No image is published, no cloud resource is created, and no production data is used.

The packaged entry point serves the protected shell with authentication unavailable. It accepts no `TRADING_` configuration overrides and loads no local authentication/database credentials. Authentication and database integration remain covered by the separate Python and disposable PostgreSQL suites. This package is a local rehearsal, not a functioning hosted sign-in deployment. The [Supabase readiness checklist](supabase-readiness.md) records that distinction and the remaining work.

## Run the checks

After [Python setup](development.md#local-python-api), start a local Linux Docker Engine 28+ with Compose, BuildKit, and cgroup v2. Reserve loopback port 8443. From the repository root:

```powershell
python scripts/checks.py operations
python scripts/checks.py database
```

`operations` builds the application, generates a one-day self-signed certificate for `127.0.0.1`, starts a uniquely named `trading-package-<random>` Compose project, tests HTTPS, records measurements, and removes that project's containers/network/certificate files. The test client trusts only its temporary certificate; system/browser trust stores are unchanged. Unknown issuers and wrong hostnames must fail certificate verification. The endpoint exists only during the check at `https://127.0.0.1:8443`.

`database` creates a disposable PostgreSQL source and, for recovery, a separate disposable destination. The persistent development database is not modified. The recovery test generates two synthetic owners, saves distinct preferences and account/source and instrument/position mapping history, rotates identifier keys, creates an authenticated session through the synthetic provider harness, and restores the export as described below.

Reports in ignored `.cache/operations/report.json` and `recovery-report.json` contain only timing, memory/size measurements, and aggregate counts. Keys, credentials, session cookies, source rows, and certificates are never uploaded as CI artifacts. Image/build caches remain local. Package commands have bounded timeouts and fail on unavailable tools or unsuccessful checks.

If interrupted, identify the exact Compose project using its labels and `.cache/operations/run-*/project.json`. Retained certificate paths can also be found in that gateway's read-only mounts. Stop only that matching rehearsal project, then remove its matching temporary directory after checking the absolute path is within `.cache/operations`. Do not prune unrelated containers, images, volumes, or the development database. Failed Docker cleanup retains the temporary files needed to recover that run.

## Build and runtime boundaries

- [Dockerfile](../infra/application/Dockerfile) pins Python 3.14.9, Node 22.23.2, and uv 0.13.5 by version and image digest. npm 12.0.2 and the committed lockfiles provide the dependency versions. Frontend install scripts are disabled; only the explicit protected build command runs. The final image contains runtime Python dependencies/application modules and protected static assets, without npm, uv, test fixtures, migration sources, or development dependencies.
- [.dockerignore](../.dockerignore) excludes everything except the allowlisted build inputs. Git history, credentials, local caches, statement files, prebuilt output, and fictional financial fixtures stay outside the build context. Repository checks reject changes that broaden this policy.
- Both services run as UID/GID `10001`, with read-only roots, all Linux capabilities dropped, no privilege escalation, core dumps disabled, and a 16 MiB non-executable temporary filesystem. Neither service mounts the Docker socket. Only the gateway mounts temporary TLS files and its configuration, all read-only.
- The gateway publishes only `127.0.0.1:8443`. The API shares its network namespace and listens on `127.0.0.1:8000`; it publishes no port. The dedicated bridge disables container peer traffic. Outbound access is **not** blocked by this bridge; the locked package has no configured provider calls. Hosted outbound allowlisting remains a separate requirement. An internal-only bridge did not publish the required host port in the local Docker environment, so it is not used as an assumed egress control.
- [Nginx configuration](../infra/application/nginx.conf) permits TLS 1.2/1.3, disables session tickets/access logs, bounds bodies to 4 KiB, and limits timeouts. It requires the exact loopback Host, overwrites the forwarded scheme, and strips other forwarding headers. Uvicorn trusts only the loopback proxy; the application rejects plaintext request scopes. Direct plaintext on the HTTPS port is rejected.
- Responses retain no-store, CSP, frame denial, nosniff, and no-referrer; the gateway adds a short local HSTS policy. Unknown paths, demo routes, private files, and unavailable authentication routes never become an HTML fallback. HTTPS cookie/origin tests use an injected synthetic service in the test process; the package itself has no fake sign-in option.
- Docker logging is bounded to two 1 MiB files per service. API logs retain only the existing sanitized request status/correlation fields. A failed build or runtime check does not print captured Docker output containing configuration.

Digest pinning fixes the build inputs, not a permanent vulnerability verdict. Python/npm advisory checks run separately; OS image advisory scanning, image signing/provenance verification, automated pin updates, and an image registry release process remain unimplemented hosted-release requirements. [Docker resource controls](https://docs.docker.com/reference/compose-file/services/), [uv image integration](https://docs.astral.sh/uv/guides/integration/docker/).

## Resource evidence

Measured on local Docker Desktop/Linux on 24 October 2026 (IST). The workload was 80 HTTPS requests to the locked shell, JS/CSS, and liveness, with concurrency four. The first successful run took 0.571 seconds for the workload; this is a small smoke workload, not a throughput benchmark.

| Service | Hard memory limit | Idle cgroup memory | Peak cgroup memory | CPU limit | PID limit |
| --- | --- | --- | --- | --- | --- |
| Python API, one worker | 256 MiB | 76.85 MiB | 77.10 MiB | 0.75 CPU | 64 |
| HTTPS gateway, one worker | 64 MiB | 6.18 MiB | 6.91 MiB | 0.25 CPU | 32 |

Cgroup measurements include charged memory/page cache and are not process RSS. The runner records Docker-reported image sizes separately. Both services disable container swap (`memswap_limit` equals the memory limit), and verification checks the actual Docker limits, port mapping, read-only writes, and OOM status. Limits total 320 MiB; host OS, Docker, build processes, database tests, and future jobs require additional memory. Builds and database tests are not intended to run on the small Oracle deployment VM.

No authenticated/provider calls, imports, financial calculations, backup production workload, Oracle CPU/storage, or host swap behavior were measured. The existing application database pools remain two connections per runtime role and two per authentication role, no overflow, with bounded waits; the locked package opens none. The planned AMD host/swap design still needs [host-level measurements and protected swap](operations.md#oracle-application-host).

## Encrypted foundation recovery

[Recovery functions](../backend/trading_db/recovery.py) accept only guarded disposable `trading_test` clusters with verified project markers, PostgreSQL 17, and administrative test credentials. There is no development/hosted export or restore command. The automated exercise is the reproducible command above, with assertions in [the recovery test](../backend/database_tests/test_recovery.py).

1. Export a consistent repeatable-read snapshot of `owners`, `owner_identities`, `workspace_preferences`, `auth_revocations`, `security_events`, `financial_accounts`, `account_currencies`, `source_accounts`, `source_account_mappings`, `fund_schemes`, `instruments`, `instrument_listings`, `instrument_identifiers`, `instrument_mappings`, `account_positions`, `source_observations`, `import_batches`, `staged_rows`, `staged_values`, `review_decisions`, `financial_events`, `event_components`, `quantity_movements`, `cash_movements`, `lots`, `lot_observations`, `lot_components`, `snapshot_records`, `snapshot_components`, `snapshot_selections`, `market_observations`, `market_selections`, `event_provider_identities`, `event_evidence_links`, and `indmoney_events`. Bound it to 1,000 rows per table and 4 MB of plaintext. Reject uncovered application tables/columns and unsupported schema revisions.
2. Store a format-14 manifest containing application version, PostgreSQL major, migration revision `0018_indmoney_authorization`, and a digest of migration sources. Encrypt the entire object with `cryptography` Fernet authenticated encryption. Plaintext is processed in memory, never written as a dump. This is a bounded foundation record format, not `pg_dump` or a general database backup.
3. Persist only the encrypted object and a separately located recovery key in private temporary directories. Recover identifier keys from a third private directory and validate all encrypted account and provider transaction references before export/restore writes. Read each input back independently for the drill. These directories share the test machine; this tests separate recovery inputs, not independent off-site custody or disaster recovery.
4. Bootstrap a fresh cluster with new database passwords and replay committed migrations to reconstruct roles, schemas, constraints, triggers, grants, and forced row policies. Validate the manifest, schema coverage, owner, and RLS flags. Require every application table to be empty. Insert allowlisted columns with bound parameters in one locked transaction; failures roll back all restored records.
5. Exclude `auth_sessions`, `auth_admissions`, `indmoney_connections` and `indmoney_attempts` entirely, including encrypted provider state. A restored installation requires explicit INDmoney reconnection; audit events remain available. Write a new revocation cutoff for every restored owner, retaining any later existing cutoff. Old cookies and admissions cannot create an active application session. New authentication is required; provider-side global revocation/identity recovery still needs its own procedure.
6. Compare durable rows, counts, preference/source/mapping revisions, archive state, constraints, policy definitions, role attributes, and table/column grants with the source. Test cross-owner read/write denial, missing context, role separation, and rejection of the former session cookie. Reject a wrong key, tampered object, incompatible manifest, nonempty target, or a late constraint failure without partial writes.

The initial run restored two owners, two identities, two preference rows, and two security events from a 2,872-byte encrypted object. It created two revocation cutoffs and restored zero sessions/admissions. Export, destination setup, restore, and assertions completed in 9.753 seconds, excluding source setup and final destination cleanup. This tiny exercise does not establish the provisional production recovery objectives.

The export includes account/source, instrument/position identity evidence/staging/review records and posted/pending event/movement, lot/correction and snapshot/selection histories, but no statement binaries, Supabase-managed identities, role passwords, or encryption keys. Formats 1–13 objects require their matching repository/schema to restore before a forward upgrade; the current reader rejects them. See [the snapshot recovery contract](snapshot-evidence.md#migration-and-recovery) and [account key custody](accounts-source-mappings.md#migration-and-recovery). Future schemas require an explicit format/compatibility update; incomplete coverage fails closed. The restore path reconstructs permissions from the repository and does not execute SQL supplied by a backup. Real backup retention, off-site key custody, scheduling, production volume tests, and provider recovery remain in [operations](operations.md) and [Supabase readiness](supabase-readiness.md).

## Verification record

Local checks on 24 October 2026 passed: 264 Python tests, 186 real PostgreSQL tests (including the separate-cluster restore), 556 frontend tests, 17 verification-helper tests, Ruff, strict application typing, both frontend builds, package/TLS/resource checks, documentation links, workflow validation, and repository secret scans. Python/npm audits reported no known dependency vulnerabilities. The demo build retains its existing bundle-size warning; the protected build succeeds separately. These results do not include an OS image advisory scan or hosted Supabase checks.

GitHub runs the same five check groups against the pushed revision and proposed merge. Actual CI results are recorded in the PR, independently of this local record. Step 4 now adds [exact values](financial-values.md), [account/source persistence](accounts-source-mappings.md), and [instrument identities](instrument-identities.md). [Step 4D.1](import-staging.md) adds normalized synthetic staging and durable review; file ingestion remains future work.
