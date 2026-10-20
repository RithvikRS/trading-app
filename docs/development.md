# Development workflow

Deliver small, reviewable features with updated documentation and conventional commits. The owner's standing instruction includes pushing the approved feature branch and opening or updating its PR after committing. Approval of a step does not authorize later stages, merging, application publishing, or deployment.

## Feature cycle

1. Define one concrete change, its user-visible result, relevant security implications, and acceptance criteria.
2. Obtain approval for that step. Reuse existing authorization within the approved scope.
3. Inspect repository instructions and the current worktree; preserve unrelated user changes.
4. Implement the change and run checks appropriate to its behavior and risk.
5. Update the affected documentation, including changed assumptions, limitations, and recovery procedures.
6. Review the diff for accidental personal data, secrets, generated files, and unrelated changes.
7. Create a conventional commit containing the completed feature and its documentation.
8. Push the feature branch to the configured repository and open or update its PR using the agreed template. Reuse an existing PR for the branch rather than creating a duplicate.
9. Report the commit, PR link, checks, result, and any limitations. Wait for approval before starting the next step or merging.

Use the current suitable checkout. When a new branch is needed, use the `codex/` prefix unless the user requests another name. Do not create unnecessary worktrees or rewrite existing history. Push and PR creation are authorized as part of the approved workflow; merging, application publishing, and resource provisioning require separate authorization.

Use the [pull request standard](pull-requests.md) for branch, review, and merge requirements. Keep one coherent feature per PR, retain small conventional commits during development, and squash merge the approved PR with a conventional message. The current integration target is `dev`. The owner's explicit merge approval and separate deployment approval are required.

Keep GitHub authentication local to the development computer. On Windows, use Git Credential Manager with Windows Credential Manager as its credential store; do not add a GitHub connector to the Codex account for this workflow. Complete sign-in through the normal GitHub authorization flow. Never print tokens, include them in commands or remote URLs, or save them in repository files. Local credential-store configuration is machine configuration and must not contain credentials in tracked documentation.

## Commit convention

Use `type(scope): concise description`. Examples of future increments:

```text
docs(plan): define scope and implementation roadmap
chore(backend): initialize Python API tooling
feat(ui): add responsive portfolio overview
feat(auth): require authentication for portfolio access
feat(imports): preview mutual fund statement transactions
feat(banking): import HDFC account transactions
fix(imports): preserve repeated payments during deduplication
```

Keep each commit coherent and reviewable. A complete feature can include its meaningful tests and documentation in the same commit. Split unrelated capabilities rather than collecting an entire roadmap stage into one commit. Never include live statements, credentials, database dumps, or identifying fixtures.

## Validation

Choose tool versions and commands during the approved setup step. Proposed tooling is Python formatting/linting and pytest for backend behavior, TypeScript checks and component tests for frontend behavior, and browser tests for important user flows.

| Change | Required evidence |
| --- | --- |
| Documentation | Review for consistency, accurate status, working local links, and clean whitespace |
| Financial calculations | Known-result fixtures, precision/rounding cases, missing-history behavior, and reconciliation |
| Imports | Duplicate/overlap cases, legitimate repeated transactions, malformed files, failure atomicity, and source attribution |
| Authentication and authorization | Invalid/expired session rejection, ownership isolation, CSRF/session behavior, and privilege checks |
| UI | Relevant interaction checks, keyboard/mobile review, readable states, and safe display of imported text |
| Connectors | Sanitized contract fixtures, pagination, limits, expiration/revocation, retries, and idempotent writes |
| Migrations and deployment | Migration/recovery validation, resource checks, database hardening, and a successful restore |

Use tests for meaningful behavior and risks. Documentation-only changes do not require application tests or introducing a test framework. Run the checks relevant to the change and broaden them when failures or new concerns justify it.

Dependency and secret checks, access controls, and secure storage must be established before real-data development. Use a separate local database and synthetic data rather than the production Supabase project for routine tests.

## Documentation upkeep

- Update [the product plan](plan.md) when scope, stage status, or acceptance criteria change.
- Update [architecture](architecture.md) for schema rules, financial definitions, and component decisions.
- Update [security](security.md) when trust boundaries, permissions, data retention, or controls change.
- Update [integrations](integrations.md) after provider verification; record scope, limits, and the date checked.
- Update [operations](operations.md) with actual setup, backup, restoration, monitoring, and incident procedures as they are implemented.
- Keep [the PR standard](pull-requests.md) and [GitHub PR template](../.github/pull_request_template.md) consistent when review or merge requirements change.
- Keep [the README](../README.md) accurate about what works and how to run it. Do not present planned controls as implemented protections.

Record significant decisions with their rationale and consequences in the relevant document. Add separate decision records only when the history becomes difficult to follow there. Never put private credentials, account details, or full incident payloads in documentation.

## Current stopping point

Step 1 planning documentation is complete. The approved follow-up covers the PR standard, GitHub PR template, conventional commits, branch push, and opening a PR into `dev`. After opening the PR, stop and wait for review and further approval. The next proposed implementation step is an overview UI prototype using synthetic data, with its exact scope and acceptance criteria agreed before implementation. Backend scaffolding, dependency installation, provider access, and infrastructure provisioning remain unstarted. CI checks and GitHub protection settings are documented requirements, not configured controls.
