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
| `npm run build` | Type-check and build static output into `dist/` |
| `npm run check` | Tests and production build |
| `npm run preview` | Serve `dist/` at `http://127.0.0.1:4173` |
| `npm audit` | Installed dependency advisories |

The project `.npmrc` disables dependency lifecycle scripts. Keep that restriction unless a script has been inspected and a narrow build-time need documented. Both servers bind to loopback with strict ports; do not expose them to a LAN, tunnel, or public host. The backend and databases are not required for this prototype.

## Planned Python and database foundation

[Step 3](foundation-plan.md) adds the Python scaffold, locked dependencies, security/CI checks, isolated local PostgreSQL, migrations, restricted roles, and authenticated browser/API tests incrementally. Framework-specific setup follows the [authentication comparison](authentication-options.md); no backend install/run or database bootstrap commands exist yet. The current frontend commands remain valid.

Tests must use explicitly named disposable databases and synthetic identities. Destructive test setup must reject hosted or non-test connection strings. Test authentication adapters stay outside the deployed runtime; no environment variable or debug endpoint may grant an owner identity in production. Hosted Supabase/identity checks, where needed, run separately from ordinary local/PR tests and report their actual evidence.

## Feature cycle

1. Define the user-visible result, security implications, and acceptance criteria.
2. Inspect the worktree and preserve unrelated changes. Refresh remote state and resolve divergence without force pushes or rewriting shared history.
3. Implement, verify relevant behavior, and update documentation.
4. Review the complete diff for defects, secrets, personal data, generated files, and unrelated work.
5. Commit the completed feature and documentation on `dev`. Push `dev` and reuse its open PR into `main` when one exists.
6. Record actual checks and evidence. Resolve findings and rerun affected checks.

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

CI, automated secret scanning, and GitHub branch protections remain to be configured. Record local evidence honestly. Establish access controls, secret handling, and protected storage before introducing real data. Future database tests use a separate local instance with synthetic fixtures, never deployed Supabase.

## Documentation upkeep

Update the plan for scope/status, architecture for component/financial decisions, security for trust boundaries, integrations for verified provider behavior, and operations for actual recovery/deployment procedures. Keep README commands and the PR template accurate. Record significant decisions with their rationale; exclude credentials, account details, and full incident payloads.
