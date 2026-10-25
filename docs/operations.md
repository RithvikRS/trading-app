# Deployment and recovery plan

The current local schema is `0021_credit_statement_evidence`. [Step 9B.4](credit-statement-evidence.md) extends the [bounded recovery rehearsal](local-packaging.md#encrypted-foundation-recovery) to format 17: 48 application tables, 44 retained durable tables and four explicitly omitted live session/admission/connector tables. Credit identities, source handles and mapping history retain their owners and revisions. Immutable statement observations bind exact historical mappings/accounts and retain independent INR checkpoints, dates, missing values and decimal spelling. Restore inserts source handles before mappings, then observation parents before statement children; deferred predecessor and reciprocal parent/child keys validate the complete transaction. These are unselected reported observations, not current liability, movements, payment status or verified provider evidence.

[Step 6B](indmoney-authorization.md) introduced schema `0018_indmoney_authorization` and recovery format 14, covering 43 application tables at that increment. Connector audit events remain retained; live connector credentials/attempts remain deliberately omitted. Restore requires fresh authentication and explicit reconnection. Local versioned connector keys and encrypted application registration remain separate from database/backup custody. Hosted secrets, certificate identity, egress and provider-specific recovery remain unverified.

The intended hosted topology is a Python application and static frontend on Oracle Cloud, with PostgreSQL hosted by Supabase. Deployment, accounts, secrets, and automation have not been provisioned. Hosted settings below remain requirements or provisional targets. [Step 3G](local-packaging.md) implements a locked local HTTPS package, resource measurements, and an encrypted synthetic restore exercise; Stage 11 remains the hosted rollout. The [Supabase checklist](supabase-readiness.md) records dedicated non-production checks separately from local tests. Those checks remain unperformed until the actual project/network/credentials are available.

The [Step 3A process](api-foundation.md) is local-only and explicitly rejects hosted environment names. It is not a deployment artifact; its limits have not been measured on Oracle. Supabase Auth on Free is selected, but no identity project or paid feature is enabled.

## Oracle application host

Use the available AMD VM if resource checks support the workload. Oracle documents 1 GB RAM and burstable CPU for the Always Free AMD micro shape, so imports must be measured under realistic constraints. Build frontend assets and container images locally or in CI rather than on the production VM. See [Oracle Always Free resources](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm).

Start with one API worker and one background job at a time. Measure idle usage and peak memory during parsing, reconciliation, and backup operations. Keep database connections small, queries bounded, and log retention finite. Avoid sustained swapping as normal operation.

A 2 GB swap file is a provisional starting point, subject to available storage and encrypted-storage design. Swap is slower than RAM and can hold sensitive process memory. Verify permissions, encryption, boot behavior, and crash-dump policy before enabling it. Adding swap does not increase CPU capacity or make an overloaded parser safe.

Keep service data on persistent protected storage. Use restricted SSH keys and private administrative access, apply OS patches, constrain container privileges, and expose only the entry points required by the selected private access or identity gateway. The hosted application must not publish a local PostgreSQL port.

Always Free instances can be reclaimed under Oracle's inactivity policy. Recovery must not depend on the original VM remaining available. Store infrastructure configuration and application versions in Git, with secrets and personal data managed separately.

## Supabase configuration

Use a dedicated production project and local PostgreSQL for development. Keep any provider integration-test project separate from production; a local application database does not automatically provide the selected managed identity service. Authentication service, recovery email, and account-session features must be budgeted separately according to the [authentication decision](authentication-options.md). Select a suitable region near the application host while considering data residency and provider availability. Confirm the actual plan and limits before creation.

Configure source address restrictions for database and pooler access, certificate-verified TLS, unexposed financial tables, disabled unused Data API access, and separate runtime/migration/backup roles. Enable MFA on the administrative account. Verify restrictions with negative tests from an unauthorized source as well as successful application connections.

Free-plan limits and inactivity pausing must be monitored. Keep statement binaries in private file/object storage rather than consuming the database allocation. Bound provider payload retention, historical price scope, and job logs. Monitor actual database usage before setting retention thresholds. See [Supabase pricing](https://supabase.com/pricing) and [project pausing](https://supabase.com/docs/guides/platform/free-project-pausing).

## Backup requirements

Supabase recommends regular exports and off-site backups for free projects. Provider-managed availability is not a substitute for independently recoverable copies. See [Supabase backups](https://supabase.com/docs/guides/platform/backups).

Provisional targets for the personal tracker are a recovery point within 24 hours and restoration within one day. Confirm these targets, retention, bandwidth, and cost before hosted use. If free-tier limits cannot support the agreed recovery targets, revise the hosting or backup plan before deployment rather than silently weakening recovery. Future trade execution requires a separate durability and recovery design.

- Schedule encrypted database exports at least daily if the agreed quota/bandwidth budget supports them; take an additional recoverable checkpoint before migrations or material imports.
- Retain a proposed seven daily and four weekly restore points, subject to the chosen storage budget and user retention preference. Estimate export traffic because full dumps can consume free-tier egress quotas.
- Keep copies outside the application VM. Use separate credentials and narrowly scoped upload permissions; restrict deletion of retained backups. Evaluate versioning or immutable retention where available.
- Back up retained source documents separately from the database, with integrity hashes and metadata linking them to import batches. Database backups do not contain external file contents.
- Include schema version, application version, required extensions, and role/policy reconstruction information. Keep encryption keys, recovery credentials, and MFA recovery material protected separately from backup objects.
- Select and document the backup destination before deployment. OCI Object Storage is a candidate, with a separate account or independent secondary copy considered for account-compromise recovery. Shared cloud credentials are not an independent security boundary.
- Alert on failed exports, missing objects, checksum failures, and overdue restore exercises. Record the date of the last verified restore.

## Restore exercise

Before hosted use, restore a representative encrypted backup into an isolated environment using separately recovered keys and the documented role setup. Disable provider jobs and outbound financial integrations in the recovery environment.

Verify decryption, schema/migration compatibility, ownership policies, record counts, representative balances, import provenance, and any retained source files. Confirm that jobs do not replay imports incorrectly and credentials are not exposed in the restored environment. Measure elapsed time and data loss against the agreed recovery targets. Repeat after backup/schema changes and on a defined schedule, provisionally monthly.

Run `python scripts/checks.py database` for the implemented synthetic foundation, account/source, instrument identity and evidence/review drill; see [its exact scope and evidence](local-packaging.md#encrypted-foundation-recovery). Development/hosted restores and general financial-volume backups require a separate implemented procedure. Identifier key versions are recovered separately; see [account key custody](accounts-source-mappings.md#local-custody-and-rotation). A migration rollback must preserve data; destructive schema changes require a reviewed recovery path. Test backup restoration before relying on it as the rollback method.

## Monitoring and incident response

Monitor application health, authentication failures, unexpected permission changes, connector errors, stale data, database size, disk capacity, memory/swap, and backup age. Choose a notification channel during deployment planning; no alerts or recurring jobs are created by this planning step. Alert on meaningful failures and actionable changes without including financial payloads.

For suspected compromise, restrict access, pause affected imports, revoke exposed sessions and provider tokens, rotate secrets, and preserve sanitized evidence. Determine whether financial records changed before restoring or resuming synchronization. Recovery includes checking provider-side activity if a credential could authorize trades. Record what happened, affected assets, remediation, and follow-up tests.

## Deployment acceptance

Require a successful production build, reviewed migration, protected entry point, verified database restrictions, security release gates, a restore exercise, and resource checks with a representative import. Confirm that failures retain last-known-good data and are visible to the owner.

Record deployed versions, configuration decisions, backup location and retention, key-recovery procedure, actual resource measurements, known limits, and the next maintenance review. Revisit the architecture before sustained memory pressure, database quota exhaustion, public multi-user access, or trading execution.

[Step 4D.2](financial-events.md#compatibility-and-recovery) advances the local schema to `0009_financial_events` and recovery format 5. The bounded disposable recovery exercise covers 24 durable tables plus the two deliberately omitted session/admission tables. Older objects require restoration with their matching release before a tested forward upgrade.

[Step 4D.3](lot-evidence-corrections.md#migration-and-recovery) advances the local schema to `0010_lots_corrections` and recovery format 6, covering 27 durable tables plus two omitted session/admission tables. Disposable downgrade refuses once version-3 evidence, lots or correction versions exist. Older encrypted objects require their matching release before forward migration; production backup operations remain separate.

[Step 4E.1](snapshot-evidence.md#migration-and-recovery) advances the local schema to `0011_snapshots` and recovery format 7, covering 30 durable tables plus two omitted session/admission tables. Downgrade remains disposable-only and refuses retained snapshot/selection records, including those originating from older normalization contracts. The runner restores forced policies before commit and rolls back failed safety guards. Older recovery objects require their matching release/schema before forward migration.

[Step 4E.2](market-evidence.md#ownership-and-recovery) advanced the schema to `0012_market_evidence` and recovery format 8, covering 32 durable tables plus the two omitted session/admission tables. Market corrections, missing values, exact rates and cleared/selected history participate in the encrypted restore drill. No market download or refresh scheduler runs. Populated market tables cannot be downgraded.

[Step 4F.1](event-evidence.md) advances the schema to `0013_event_evidence` and recovery format 9, covering 34 durable tables and two omitted session/admission tables. Rotate both account and provider transaction references before retiring old identifier keys. The restore drill verifies custody revisions, exact source links and historical event retries. No provider connection or import completion endpoint is enabled.

[Step 4F.3.1](statement-boundaries.md) introduced schema `0014_statement_boundaries` and recovery format 10. The 36-table inventory is unchanged; normalized cash date basis and staged checkpoint boundaries are included. Populated contract-5 evidence cannot be downgraded. Restore older objects with their matching source revision before a tested forward migration.

[Step 4F.3.2a](completion-preflight.md) advances the schema to `0015_completion_baseline` and recovery format 11, preserving the 36-table inventory. The encrypted two-owner restore drill also compares financial baseline tokens across key rotation and recovery. The new guard requires read-committed isolation and a short owner transaction.

[Step 4F.3.2c](reconciled-completion.md) advances the schema to `0017_reconciled_completion` and recovery format 13 with 40 application tables. Receipts, dispositions and comparison inputs are immutable; populated comparison tables prevent downgrade. Recovery verifies historical limited/full receipt replay after corrections and private-reference rotation. Complete-activity statements require successful source and combined equations in every supplied native scope.
