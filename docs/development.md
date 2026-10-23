# Development

Deliver one coherent feature at a time, with meaningful checks, updated documentation, and conventional commits on `dev`. Open or update its pull request into `main` using the [PR standard](pull-requests.md).

## Local frontend

The prototype uses React, TypeScript, and Vite. Node 22.22.2+ is required by the selected toolchain; Node 22.23.2 and npm 12.0.2 were used for initial development. Direct dependencies have exact versions and `package-lock.json` locks the tree.

From `frontend/`:

| Command | Purpose |
| --- | --- |
| `npm ci` | Install locked dependencies |
| `npm run dev` | Start at `http://127.0.0.1:5173` |
| `npm run test` | Financial fixture, preference, component, structural accessibility checks |
| `npm run test:watch` | Tests while editing |
| `npm run typecheck` | TypeScript checks without emitting files |
| `npm run build` | Type-check both applications; build prototype `dist/` and protected `workspace/dist/` |
| `npm run build:workspace` | Rebuild only the protected workspace assets; restart the API to load them |
| `npm run check` | Tests and production build |
| `npm run preview` | Serve `dist/` at `http://127.0.0.1:4173` |
| `npm audit` | Installed dependency advisories |

The project `.npmrc` disables dependency lifecycle scripts. Keep that restriction unless a script has been inspected and a narrow build-time need documented. Both servers bind to loopback with strict ports; do not expose them to a LAN, tunnel, or public host. The backend and databases are not required for this prototype.

The separate [protected workspace](protected-workspace.md#separate-builds-and-local-entry) builds to `frontend/workspace/dist/` and is served through FastAPI with `TRADING_API_FRONTEND_ENABLED=true`. The prototype commands above continue to use fictional data.

## Local Python API

The [Step 3A scaffold](api-foundation.md) uses Python 3.14.9 and uv 0.13.5 with exact direct versions and `backend/uv.lock`. Supabase Auth with FastAPI is selected; the default liveness-only mode needs no authentication/database credentials. The frontend commands above remain valid independently.

For a repository-local Windows setup, run from the repository root with an existing Python installation. This installs tooling into ignored directories and leaves the system Python and Windows registration unchanged:

```powershell
python -m venv .cache/api-tools
& .cache/api-tools/Scripts/python.exe -m pip install --disable-pip-version-check --only-binary=:all: --index-url https://pypi.org/simple uv==0.13.5
$env:UV_CACHE_DIR = Join-Path (Get-Location) '.cache/uv'
$env:UV_PYTHON_INSTALL_DIR = Join-Path (Get-Location) '.cache/python'
$uv = Join-Path (Get-Location) '.cache/api-tools/Scripts/uv.exe'
& $uv python install 3.14.9 --no-bin --no-registry
Set-Location backend
& $uv sync --locked
& $uv run --locked python -m trading_api
```

Open [API liveness](http://127.0.0.1:8000/api/v1/health/live), which returns only `{"status":"ok"}`. Stop with Ctrl+C. The API binds only to `127.0.0.1`; no UI connection or database is required. Do not substitute a public bind, reload/debug mode, or alternate server command. A port conflict fails startup rather than selecting another port.

In a new shell, recreate `$uv` and the two `UV_` directory variables from the repository root before entering `backend/`. If the pinned uv is already on PATH, use `uv` in place of `& $uv`; keep the same pinned Python, lockfile, and local-only entry point. Initial downloads require network access. Subsequent checks can add `--offline` after `run` once the locked environment/cache exists.

From `backend/` with the setup above:

| Command | Purpose |
| --- | --- |
| `& $uv sync --locked` | Install exactly the committed lockfile; reject stale dependency declarations |
| `& $uv run --locked python -m trading_api` | Start the local API |
| `& $uv run --locked pytest` | Configuration, HTTP, error/log privacy, workspace/authentication validation, and real local process tests |
| `& $uv run --locked ruff check .` | Python lint |
| `& $uv run --locked ruff format --check .` | Formatting check |
| `& $uv run --locked mypy` | Strict application type checks |

`backend/.env.example` lists the supported settings, including opt-in authentication and protected frontend delivery. It is not loaded automatically. Set `TRADING_API_ENVIRONMENT` to `development` or `test` and `TRADING_API_PORT` to a valid unprivileged port when needed. Unknown application settings and hosted modes fail closed. Error logs intentionally omit values; check spelling and the allowlist in [the scaffold contract](api-foundation.md#configuration-and-local-entry-point).

## Repeatable local checks and CI

Run `python scripts/checks.py all` from the repository root after the setup above and selecting Node 22.23.2/npm 12.0.2. The launcher also accepts `backend`, `frontend`, `repository`, `database`, or `operations`. Start a local Docker Engine 28+ with Compose before database, operations, or all checks. It performs locked installs and fails on incomplete checks. See [verification](verification.md) for tool pins, network/loopback requirements, secret-scan scope, and the matching five CI jobs.

## Local PostgreSQL

[Step 3C](database-foundation.md) provides `python scripts/database.py up`, `migrate`, `status`, and `down` from the repository root. Run `up` then `migrate`; the service binds to `127.0.0.1:55432`. `down` retains the volume and generated credentials. `python scripts/checks.py database` creates its own disposable cluster and does not need the development service. Read the database runbook before changing local credential files or storage.

[Step 3D](ownership-isolation.md) implements the internal ownership and row-policy boundary. `migrate` now reaches `0006_accounts_sources` without seeding owners. Run `up` first to add the separate authentication credential. [Step 3E.1](authentication-foundation.md) adds the internal Supabase adapter and explicit `scripts/authentication.py provision-owner`/`smoke` tools. Read that runbook before configuring a dedicated test project. [Step 3E.2](browser-sessions.md) adds opt-in browser routes and server sessions. Initialize the private key with `python scripts/authentication.py init-session-key`; set `TRADING_API_AUTH_ENABLED=true` only after configuring the dedicated provider. Email recovery is separately off by default. The runbook also covers `revoke-owner`, session limits, and recovery. Hosted verification remains absent. [Step 4B](accounts-source-mappings.md) adds internal financial account persistence with independently protected identifier keys; the protected UI remains empty.

Tests must use explicitly named disposable databases and synthetic identities. Destructive test setup must reject hosted or non-test connection strings. Test authentication adapters stay outside the deployed runtime; no environment variable or debug endpoint may grant an owner identity in production. Hosted Supabase/identity checks, where needed, run separately from ordinary local/PR tests and report their actual evidence.

## Feature cycle

[Step 4A financial values](financial-values.md) are pure Python contracts in `trading_api.finance`. Run the focused examples with `uv run --locked pytest tests/test_finance.py` from `backend/`, or include them through the normal shared backend checks. No database or provider configuration is needed for these tests.

1. Define the user-visible result, security implications, and acceptance criteria.
2. Inspect the worktree and preserve unrelated changes. Refresh remote state and resolve divergence without force pushes or rewriting shared history.
3. Implement, verify relevant behavior, and update documentation.
4. Review the complete diff for defects, secrets, personal data, generated files, and unrelated work.
5. Commit the completed feature and documentation on `dev`. Push `dev` and reuse its open PR into `main` when one exists.
6. Record actual checks and evidence. Resolve findings and rerun affected checks.
7. Merge the completed PR automatically once final-revision checks and review requirements pass, then synchronize the persistent branches. Every increment retains its own PR record.

Use the two persistent branches rather than creating a branch per routine increment. Keep unrelated work out of a PR under review. Merge commits preserve shared ancestry; fetch and fast-forward `dev` to `origin/main` after a merge. Inspect divergence when fast-forwarding is impossible. Deployments have a separate release process.

Keep GitHub authentication local to the development computer. On Windows, use Git Credential Manager with Windows Credential Manager. Sign in through the normal GitHub flow; never print tokens, embed them in URLs, or save them in the repository. Credential-store configuration is local machine configuration.

## Commit convention

Use `type(scope): concise description`, for example:

```text
feat(ui): add responsive portfolio overview
feat(auth): require authentication for portfolio access
fix(imports): preserve repeated payments during deduplication
docs(operations): describe backup restoration
```

A feature can include its tests and documentation in one commit. Split unrelated capabilities into separate increments. Keep live statements, credentials, dumps, and identifying fixtures out of every commit.

## Validation

| Change | Evidence |
| --- | --- |
| Documentation | Accurate status, consistent decisions, working local links, clean whitespace |
| Calculations | Known results, precision/rounding, missing data, reconciliation |
| UI | Interactions, keyboard/mobile review, contrast, states, safe rendering |
| Imports | Duplicates/overlaps, repeated payments, malformed files, atomicity, provenance |
| Authentication | Invalid/expired sessions, ownership isolation, CSRF, least privilege |
| Connectors | Sanitized contracts, pagination, limits, revocation, retries, idempotency |
| Migrations/deployment | Recovery, resource limits, database hardening, successful restore |

Use tests for meaningful behavior and risks. Documentation-only changes do not need unrelated application tests. Component tests do not replace visual, keyboard, or assistive-technology review. Advisories are a point-in-time check, not a security guarantee.

CI and automated secret detection are defined by [the verification workflow](verification.md). GitHub branch protections remain separate settings; this change does not configure them. Record local evidence honestly. Establish access controls, secret handling, and protected storage before introducing real data. Database tests use a separate local instance with synthetic fixtures, never deployed Supabase.

## Documentation upkeep

Update the plan for scope/status, architecture for component/financial decisions, security for trust boundaries, integrations for verified provider behavior, and operations for actual recovery/deployment procedures. Keep README commands and the PR template accurate. Record significant decisions with their rationale; exclude credentials, account details, and full incident payloads.

For authenticated display preferences, apply migration `0005_preference_revisions`, build the protected frontend, and restart the API. Follow the [preference contract and recovery notes](display-preferences.md). Local tests use real disposable PostgreSQL with synthetic authentication responses; they do not create a development login bypass or configure a hosted project.
