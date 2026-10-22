# Pull request standard

Every PR delivers one coherent change, explains the resulting behavior, and provides evidence that it works. Security and financial integrity take precedence over convenience and delivery speed.

## Scope and branches

Commit and push completed changes directly to `dev`, then open or update its PR into `main`. Keep the PR focused enough to review in one sitting. Include relevant tests and documentation; separate unrelated refactoring, formatting, and dependency upgrades. Use draft status while work or verification is incomplete.

Both branches are persistent. Reuse an existing open PR for this branch pair and finish its review before adding unrelated work. Keep `main` for reviewed changes. Merges do not trigger deployment; releases have their own operational checks.

## Titles and descriptions

Use `type(scope): concise description` for commits, PR titles, and merge-commit titles:

```text
feat(imports): preview mutual fund transactions
fix(banking): preserve repeated payments during import
docs(workflow): define pull request standard and template
```

Use the appropriate Conventional Commit type. Mark breaking changes with `!` or a breaking-change footer and explain migration impact. See [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/).

Use the [PR template](../.github/pull_request_template.md). Lead with the problem and resulting behavior, adding a before/after example when useful. Write for a reviewer who has not seen the development conversation. Keep details proportional to risk. Explain why security or migration effects are inapplicable rather than leaving sections blank.

## Evidence and review

Report checks actually run and distinguish passed, failed, blocked, and unperformed checks. UI work includes desktop/mobile screenshots with synthetic data and relevant keyboard/state checks. Review the full diff for defects, unrelated changes, debug code, personal data, and secrets.

Highlight consequential decisions, resolve findings with code or a documented rationale, and repeat affected checks after changes. Material changes require fresh review. In a solo project, record self-review and validation; additional reviewers provide independent scrutiny when available. See [GitHub review guidance](https://docs.github.com/en/pull-requests/concepts/helping-others-review-your-changes).

## Security and financial integrity

Apply [security requirements](security.md) according to risk, including small changes with significant permission or calculation effects.

| Change | Review focus |
| --- | --- |
| Authentication/database policies | Unauthorized access, revocation, ownership isolation, pooled identity, least privilege |
| Imports | Unsafe files, resource limits, duplicate/repeated transactions, atomicity, reconciliation, privacy |
| Calculations | Exact arithmetic, rounding, currencies, fees, missing history, known results |
| Migrations | Data preservation, roles/policies, compatibility, backups, recovery |
| Infrastructure/CI | Exposed services, secret access, workflow permissions, dependencies |
| UI | Safe rendering, amounts, coverage/freshness, privacy, accessibility, reflow |
| Integrations | Token capabilities, consent/revocation, allowed destinations, coverage, retries, provenance |

Exploitable findings, unauthorized access, leaked credentials, and financial correctness defects block merging. Investigate scanner findings rather than disabling checks broadly. Revoke or rotate leaked credentials; removing a secret from a diff does not invalidate it. See [secret-scanning guidance](https://docs.github.com/en/code-security/concepts/secret-security/secret-scanning).

## Checks and merging

Applicable checks must pass on the final revision: source checks, meaningful tests, production builds, browser verification, dependency/security checks, and documentation consistency. Documentation-only PRs do not need unrelated tests.

[Step 3B verification](verification.md) defines three CI checks: Python checks, Frontend checks, and Repository security. Run `python scripts/checks.py all` locally and inspect all three GitHub results on the final revision before merging. The workflow uses read-only repository permissions, no production secrets, and no path-based skips. Repository branch protection/ruleset settings are separate and are not configured by the workflow; do not infer enforced merge gates from a green run.

Merge after review, passing checks, resolved findings, and satisfied security requirements. Use a merge commit with a conventional title to preserve ancestry between `dev` and `main`; do not squash or rebase this branch pair. Fetch and fast-forward `dev` to `origin/main` afterward, resolving divergence without rewriting shared history. Verify the resulting branches.

## Repository protections

The intended configuration protects `main` against direct changes, force pushes, and deletion, and requires PRs, applicable checks, and resolved conversations. Restrict write access to `dev`, prevent force pushes/deletion, and retain direct commits there. Apply protections to administrators where supported.

Verify available features for the repository's visibility and account plan before claiming enforcement. Document gaps and corresponding manual checks. This document and template do not configure repository settings. See [protected branches](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches).
