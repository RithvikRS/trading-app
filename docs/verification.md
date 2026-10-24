# Repeatable verification

The repository now has one check entry point and a GitHub Actions workflow using the same commands. All checks use synthetic data. [Step 3C](database-foundation.md) adds a disposable local PostgreSQL service for database checks. Hosted identity, production credentials, deployment jobs, and cloud permissions remain absent.

## Local commands

From the repository root, after the [Python setup](development.md#local-python-api):

```powershell
python scripts/checks.py all
```

The launcher needs Python 3.11 or newer. Backend commands run with the pinned Python 3.14.9 environment through uv 0.13.5. Node 22.23.2 is pinned in `frontend/.node-version`; npm 12.0.2 is pinned in `frontend/package.json`. Select those Node/npm versions before running frontend checks. The launcher does not change the system's Node/npm installation.

| Command | Checks |
| --- | --- |
| `python scripts/checks.py repository` | Verification-helper failure tests, workflow security policy, actionlint, local documentation links, Gitleaks detector controls, complete reachable Git history, and current source snapshot |
| `python scripts/checks.py backend` | Locked Python installation, Ruff lint/format, strict application mypy, API/authentication tests, and strict pip-audit |
| `python scripts/checks.py frontend` | Exact Node/npm versions, locked install with dependency lifecycle scripts disabled, tests/types/build, and npm audit at all reported severities |
| `python scripts/checks.py database` | Fresh PostgreSQL cluster, migration/rollback, role/RLS denial, two-owner isolation, restricted identity lookup/enrollment, session/recovery/renewal races, preference revision conflicts, account/source and instrument identity isolation, fund variants and mapping history, concurrent reference matching/rotation, identifier key recovery and rollback, durable admission, event grants, cancellation/pool cleanup, and target guards; requires local Docker Engine 28+ and Compose |
| `python scripts/checks.py operations` | Digest-pinned protected build, non-root/read-only containers, actual loopback mappings, certificate/hostname/plaintext denial, headers, route isolation, runtime limits, and bounded workload measurements; requires local Docker/Compose with cgroup v2 |
| `python scripts/checks.py all` | Repository, backend, database, frontend, and operations groups in order; stops on the first failure |

Dependencies are installed from committed lockfiles. Python audit tooling and its transitive dependencies are locked as development dependencies and are excluded from runtime-only installs. Gitleaks 8.30.1 and actionlint 1.7.12 are fetched from official release archives into ignored `.cache/check-tools/`. Archive hashes are checked before reading the binary, and the binary hash is checked on every invocation, including cache hits. `scripts/tools.json` records both hashes for Windows/Linux x86_64. Other platforms fail explicitly until verified pins are added.

Frontend test files run with one worker to keep DOM-heavy integration tests from competing for resources on local machines and CI. Per-file isolation, test assertions, and their time limits remain active. Import-inspector keyboard checks wait for cancellation's next-frame focus restoration before sending Tab, asserting restoration and containment as separate interactions.

The commands need network access for initial downloads, dependency installation, and fresh advisory queries. The API and database suites need loopback socket access. Database checks also need the local Docker socket and the digest-pinned PostgreSQL image; the first image pull requires network access. Test credentials are generated per run and removed after successful container cleanup. An unavailable audit service, missing tool, stale lock, checksum mismatch, scan error, or shallow Git history is a failure; there is no offline-success or skip switch. For a shallow checkout, fetch its complete history before running repository checks. Tool commands have a 20-minute timeout, except the clean frontend install, which allows 45 minutes for slower local filesystems. Windows invokes npm through Node directly so an install timeout terminates npm instead of leaving it behind a terminated command wrapper. Hosted CI jobs retain their independent 20-minute limit.

## Secret detection and privacy

Gitleaks uses its default rules without a baseline or repository exclusions. Inline `gitleaks:allow` comments do not suppress checks. Positive controls use a generated fictional token and an isolated temporary Git history to verify that both a current secret and a deleted historical secret are detected. A clean control must also pass, so a broken scanner cannot satisfy the negative test accidentally.

The history scan covers all reachable fetched refs. The source scan copies tracked files and non-ignored untracked files into an isolated snapshot, including uncommitted edits. Deleted files remain covered by history; ignored local credentials, virtual environments, dependencies, and build output are not copied. Symlinks/path escapes and unsupported source entries fail rather than reading outside the repository. Nested archives/binary formats and secrets outside fetched history are not guaranteed coverage. These checks do not replace careful review or prevent a secret from being committed locally.

Scanner output is captured and suppressed, with redaction enabled as an additional control. No finding report or source snippet is uploaded. A failure names the check, not its matched contents. Investigate locally with the pinned tool and redaction enabled in a private terminal; never paste findings containing private records into a PR. Revoke exposed credentials before addressing history or exceptions. Changes to scanner policy, pins, or suppression rules need explicit technical review.

## CI contract

`.github/workflows/verification.yml` runs on pushes to `dev` and `main`, pull requests targeting `main`, and manual dispatch. Every run schedules the same five named jobs: **Python checks**, **Database checks**, **Frontend checks**, **Repository security**, and **Local package checks**. No path filters or conditional skips turn documentation-only changes into a silent pass. PR runs validate GitHub's proposed merge result; push runs validate the pushed commit.

Jobs use disposable `ubuntu-24.04` runners, `contents: read`, and commit-pinned checkout/setup actions. Checkout does not retain Git credentials, and the repository-security checkout fetches complete history. Dependency caches, build artifacts, deployment environments, write tokens, production secrets, and privileged PR events are absent. npm dependency lifecycle scripts stay disabled; the explicitly requested test/build commands still execute project code.

Untrusted pull-request code is expected to execute only with that restricted context. Never switch this workflow to `pull_request_target`, introduce self-hosted runners, or pass cloud/provider credentials to it. Workflow-policy tests check the current event, permission, action-pin, cache, checkout, and command boundaries. Those tests are review aids: a contributor can propose changes to both a workflow and its tests, so they do not replace review or repository settings. [GitHub workflow security](https://docs.github.com/en/actions/reference/security/secure-use).

Branch protections/rulesets are separate settings. Adding YAML does not require checks before merging or prevent direct pushes. Configure and verify the five named checks on `main` when repository/account capabilities permit, and review the exact commit's results before merging. This increment does not change repository protection settings. No workflow publishes or deploys the application.

On 23 October 2026, GitHub reported `main` as unprotected. The repository's default workflow token permissions were read-only, and workflow-created PR approvals were disabled. The rulesets endpoint returned HTTP 403, so ruleset configuration could not be independently inspected. Treat the checks as visible verification results rather than enforced merge gates until branch protection is configured and verified.

## Updating and interpreting checks

Update versions deliberately: refresh lockfiles or published archive/binary hashes, update matching action pins and policy expectations, then run affected checks. Do not auto-fix advisories or add broad exclusions to obtain a green result. Advisory results reflect the current databases and may change without a code change; checks report known vulnerabilities, not proof of absence of vulnerabilities. Python and npm audits include development dependencies. [pip-audit](https://github.com/pypa/pip-audit), [Gitleaks](https://github.com/gitleaks/gitleaks), [actionlint](https://github.com/rhysd/actionlint).

Record local results separately from the actual GitHub run. A local pass does not prove hosted runner compatibility or configured branch protection. Database verification and its recovery limits are documented in [Step 3C](database-foundation.md). [Step 3D](ownership-isolation.md) extends the same database job with owner/RLS and connection-reuse tests. [Step 3E.1](authentication-foundation.md) adds signed-provider-response tests and controlled identity lookup. No hosted credentials are used. [Step 3E.2](browser-sessions.md) adds HTTP/CSRF/cookie tests, encrypted custody, real PostgreSQL session/recovery/revocation tests, and security-event checks. [Step 3F.1](protected-workspace.md) adds protected-client/component tests, build isolation checks, and static-delivery boundaries. The frontend check builds both applications; browser review uses synthetic responses separately from hosted authentication. [Step 3F.2](display-preferences.md) adds strict preference contracts, conflict/draft UX, revocation ordering, revision migration, and failure rollback checks. [Step 3G](local-packaging.md) adds the Local package checks job and extends Database checks with encrypted recovery into a second cluster, reconstructed roles/policies, owner isolation, rollback, and session invalidation. The package serves a locked shell; no hosted credentials, registry publication, or deployment is involved.
