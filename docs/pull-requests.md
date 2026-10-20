# Pull request standard

Approved on 21 October 2026. Every PR should deliver one coherent change, provide evidence that it works, and explain its security and financial-integrity implications. Security is the highest review priority. This standard documents the workflow; CI and GitHub protection settings will be configured in a separately approved step.

## Scope and branches

Keep each PR small enough to understand and review in one sitting. Include the feature's relevant tests and documentation, and separate unrelated refactoring, formatting, or dependency upgrades. Split a larger stage into increments with useful acceptance criteria; a line-count target must not force an unsafe or incomplete change.

Commit and push approved changes directly to `dev`, then open a PR with `dev` as the source and `main` as the target. These are the repository's existing lowercase branch names. Preserve existing local work and refresh remote state before starting. Keep `main` for reviewed changes; merging into it does not authorize or trigger deployment unless a separately approved release process is configured.

Keep conventional commits after each completed small feature. A PR may contain intermediate coherent commits, but its final scope must still represent one feature, fix, or documentation change. Use draft status while work or required verification is incomplete.

After committing an approved change on `dev`, push `dev` and open or update its PR into `main`. Reuse an existing open PR for this branch pair. Report the PR link and validation results, then wait for review; pushing and opening a PR do not authorize merging it. Since the source branch is shared across steps, complete the current review and merge before adding unrelated work.

## Titles and descriptions

Use `type(scope): concise description` for commits, PR titles, and the first line of the approved merge commit. Examples:

```text
feat(imports): preview mutual fund transactions
fix(banking): preserve repeated payments during import
docs(workflow): define pull request standard and template
```

Choose `feat`, `fix`, `docs`, `refactor`, `test`, `ci`, `build`, `perf`, or `chore` according to the change. Mark breaking changes with `!` or the conventional breaking-change footer and explain the migration impact. See [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/).

Use the [PR template](../.github/pull_request_template.md). Lead with the concrete problem and the resulting behavior. Include a before/after example when it makes the result clearer. Describe the final change for a reviewer who has not seen the chat; remove obsolete scope and abandoned approaches unless they explain a relevant tradeoff.

Keep documentation and PR text focused on the project, decisions, behavior, and validation. Omit authoring-tool credits and tool-specific operating instructions. Use the configured contributor identity for commits without adding generated attribution trailers.

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

The owner must explicitly approve merging the reviewed change into `main`. The standing workflow authorizes commits and pushes to `dev` and opening or updating its PR into `main`. It does not authorize merging or deployment. Review evidence supports the owner's decision but does not replace it.

When a distinct reviewer is available, require at least one approving review. GitHub authors cannot approve their own PRs, so a solo workflow must not depend on an impossible self-approval requirement. In that case, retain recorded self-review, applicable passing checks, and the owner's explicit merge authorization.

Merge only after the final revision has been reviewed, applicable checks pass, actionable conversations are resolved, and the security requirements are met. Use a merge commit with a conventional title to preserve ancestry between the persistent `dev` and `main` branches; do not squash or rebase this branch pair. After the approved merge, fetch the remote state and fast-forward local `dev` to `origin/main`, then push `dev` before the next step. This keeps the branches aligned without rewriting history. If a fast-forward is not possible, inspect and resolve the divergence before proceeding. Verify the merge result before reporting completion. Deployment remains a separate approval and acceptance step.

## Repository protections

When configuring GitHub, protect `main` against direct changes, force pushes, and deletion. Require PRs, applicable passing checks, resolved conversations, and reviewer approval where the reviewer model supports it. Apply protections to administrators where supported; routine development must not rely on bypassing them. Require new review for material changes after approval.

Restrict write access to `dev` and protect it against force pushes and deletion while allowing the approved direct-commit workflow. Run applicable local checks before pushing and configure checks on `dev` pushes during the approved CI step. Do not apply a PR-only rule to `dev` that contradicts this workflow.

GitHub protection availability depends on repository visibility and account plan. Verify capabilities before claiming enforcement; document any gap and the manual approval process used until it is resolved. See [protected branches](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches).

The template and this document do not configure repository settings or create CI workflows. The approved documentation workflow includes committing and pushing to `dev` and opening or updating its PR into `main`. After publishing the PR, wait for review and approval of the next step; application implementation remains unstarted.
