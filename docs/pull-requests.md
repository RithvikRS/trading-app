# Pull request standard

Approved on 21 October 2026. Every PR should deliver one coherent change, provide evidence that it works, and explain its security and financial-integrity implications. Security is the highest review priority. This standard documents the workflow; CI and GitHub protection settings will be configured in a separately approved step.

## Scope and branches

Keep each PR small enough to understand and review in one sitting. Include the feature's relevant tests and documentation, and separate unrelated refactoring, formatting, or dependency upgrades. Split a larger stage into increments with useful acceptance criteria; a line-count target must not force an unsafe or incomplete change.

Use a descriptive short-lived branch such as `codex/mutual-fund-import` and target `dev`, the current integration branch. Start from the appropriate current integration state and preserve existing local work. Select the deployment branch before configuring release automation; do not assume merging to `dev` deploys anything.

Keep conventional commits after each completed small feature. A PR may contain intermediate coherent commits, but its final scope must still represent one feature, fix, or documentation change. Use draft status while work or required verification is incomplete.

## Titles and descriptions

Use `type(scope): concise description` for PR titles and the resulting squash commit. Examples:

```text
feat(imports): preview mutual fund transactions
fix(banking): preserve repeated payments during import
docs(workflow): define pull request standard and template
```

Choose `feat`, `fix`, `docs`, `refactor`, `test`, `ci`, `build`, `perf`, or `chore` according to the change. Mark breaking changes with `!` or the conventional breaking-change footer and explain the migration impact. See [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/).

Use the [PR template](../.github/pull_request_template.md). Lead with the concrete problem and the resulting behavior. Include a before/after example when it makes the result clearer. Describe the final change for a reviewer who has not seen the chat; remove obsolete scope and abandoned approaches unless they explain a relevant tradeoff.

Keep each section proportional to risk. A simple copy correction can use a sentence per applicable section; an authentication or import change needs detailed evidence. State why security or migration effects are not applicable rather than leaving those sections blank. Link related work when available without requiring an issue for every small change.

## Evidence and review

Report the actual checks run and their results. Distinguish passed checks from checks not run, blocked checks, and manual inspection. Never mark a checklist or test as passed based only on intention. UI changes should include desktop and mobile screenshots or recordings using synthetic data, along with relevant keyboard and state checks. Screenshots, fixtures, logs, and PR text must not expose personal records or credentials.

Before requesting review, inspect the complete diff for incorrect behavior, missing documentation, unrelated changes, debug code, personal data, and secrets. Highlight the files or decisions needing particular attention. Resolve actionable comments with code or a documented explanation, rerun affected checks, and review the final diff again after changes. Material changes after approval require renewed review and approval.

GitHub recommends focused PRs, clear context, self-review, and additional attention to security-sensitive changes. See [GitHub review guidance](https://docs.github.com/en/pull-requests/concepts/helping-others-review-your-changes).

## Security and financial integrity

Apply [security requirements](security.md) to every PR. Review depth follows the change's risk, including small changes with significant permission or calculation effects.

| Change | Required review focus |
| --- | --- |
| Authentication or database policies | Unauthorized access, session expiry/revocation, ownership isolation, pooled identity handling, and least privilege |
| Statement imports | Unsafe files, resource limits, duplicates, legitimate repeated transactions, partial failures, reconciliation, and personal-data exposure |
| Financial calculations | Decimal precision, rounding, currencies, fees, missing history, and known-result examples |
| Database migrations | Preservation of existing data, role/policy changes, compatibility, backups, and a workable recovery path |
| Infrastructure or CI | Exposed services, secret access, workflow permissions, dependencies, and configuration changes |
| UI | Safe rendering, correct amounts and freshness labels, accessibility, and responsive behavior |
| Provider integrations | Actual token capabilities, credential handling, consent/revocation, approved destinations, history coverage, retries, and source attribution |

Unresolved exploitable security findings, unauthorized access, leaked credentials, and financial correctness defects block merging. Investigate scanner findings and document false positives or inapplicable results instead of disabling checks broadly. If a credential leaks, revoke or rotate it before treating cleanup as complete; removing it from a diff does not invalidate it. See [GitHub secret-scanning guidance](https://docs.github.com/en/code-security/concepts/secret-security/secret-scanning).

## Automated checks

Configure checks during approved tooling and CI work. Require the checks applicable to the changed files and behavior to pass on the final PR revision:

- Formatting, linting, and type checks for affected source code.
- Meaningful unit/integration tests, including relevant security and financial edge cases.
- Production build and browser checks for affected application flows.
- Secret scanning and dependency/security checks appropriate to source, dependencies, containers, and workflows.
- Documentation links, formatting, and consistency for documentation changes.

Documentation-only PRs do not need unrelated application tests or a new test framework. Before CI is configured, record the manual/local checks actually available and state the missing automation. Do not claim GitHub checks are enforced until the workflows and protection settings exist.

CI must use minimal token permissions and keep production credentials away from untrusted PR code. Review workflow changes as security-sensitive changes. Configure path-based checks so required checks report an intentional result rather than leaving PRs indefinitely pending.

## Approval and merging

The owner must explicitly approve merging the reviewed change. Approval to implement or commit does not imply approval to push, create an external PR, merge, or deploy. An AI review can support review but does not replace the owner's decision.

When a distinct reviewer is available, require at least one approving review. GitHub authors cannot approve their own PRs, so a solo workflow must not depend on an impossible self-approval requirement. In that case, retain recorded self-review, applicable passing checks, and the owner's explicit merge authorization.

Merge only after the final revision has been reviewed, applicable checks pass, actionable conversations are resolved, and the security requirements are met. Use squash merge with a conventional message so one feature produces one clear integration-branch commit. Verify the merge result before reporting completion. Deployment remains a separate approval and acceptance step.

## Repository protections

When configuring GitHub, protect `dev` and the selected deployment branch against direct unreviewed changes, force pushes, and deletion. Require PRs, applicable passing checks, resolved conversations, and reviewer approval where the reviewer model supports it. Apply protections to administrators where supported; routine development must not rely on bypassing them. Require new review for material changes after approval.

GitHub protection availability depends on repository visibility and account plan. Verify capabilities before claiming enforcement; document any gap and the manual approval process used until it is resolved. See [protected branches](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches).

The template and this document do not configure repository settings, create CI workflows, publish a PR, or authorize implementation. After the approved documentation commit, wait for the next step.
