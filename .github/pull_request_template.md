<!--
Keep one coherent change per PR and use a conventional title, for example:
feat(imports): preview mutual fund transactions

Follow docs/pull-requests.md. Keep details proportional to the change.
Use dev as the source branch and main as the target branch.
Focus on project behavior and evidence.
Use synthetic data in examples and screenshots. Never include credentials,
personal statements, account identifiers, or unredacted financial logs.
Document checks actually performed; do not claim planned checks passed.
-->

## Change

<!-- Explain the problem and resulting behavior. Add a before/after example or related issue when useful. -->

## Validation

<!-- List checks run and results, including relevant edge cases. Identify checks not run and why. -->
<!-- Record the locally checked commit/tree, commands and environment. Code/configuration changes require all five local groups; documentation-only changes may run repository checks with a rationale. GitHub Actions is manual and optional; distinguish actual runs from local evidence. -->
<!-- For UI changes, attach desktop/mobile screenshots using synthetic data and note relevant interaction checks. -->

## Security and financial integrity

<!-- Describe permission, credential, data-exposure, dependency, or financial-calculation changes. -->
<!-- Explain relevant protections and verification. If no impact, state why briefly. -->

## Migration and recovery

<!-- Describe database/configuration changes, compatibility, and recovery steps. -->
<!-- Use "Not applicable" when appropriate. Never include live connection strings or secrets. -->

## Documentation

<!-- Link documents updated or explain why no documentation update is needed. -->

<!--
Before requesting review: inspect the final diff and run applicable checks.
Commit completed changes on dev, push dev, and open or update its PR into main.
Resolve actionable comments and repeat affected checks after changes.
Require passing local verification of the final tree before merging. GitHub Actions is manual.
Review the final revision before merging. Deployments follow the release process.
-->
