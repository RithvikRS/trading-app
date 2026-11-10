# Supabase deployment readiness

Historical checklist: the [Oracle/Authelia decision](oracle-authelia-decisions.md) supersedes this hosted direction. Retain these findings as evidence of the existing adapter limits; use the [Oracle/Authelia migration plan](oracle-authelia-migration.md) for new deployment work. No Supabase project is required for the selected target.

Status on 24 October 2026: local packaging and synthetic recovery are implemented. **Hosted readiness is not established.** There is no dedicated Supabase test project, hosted database adapter, configured provider, Oracle deployment, or production secret. Use this checklist to collect evidence before hosted use; local success is not a substitute for these checks.

## Compatibility work before a connection

The current database tools deliberately accept only managed loopback development/test clusters. They force a loopback address, disable database TLS only for that local connection, verify the local cluster marker/PostgreSQL major, and provision roles through a local bootstrap administrator. They must not be pointed at Supabase by weakening those guards.

Add a separate hosted configuration/adapter with explicit project/endpoint identity, certificate-verified TLS, credential files outside images/source, bounded pools, and no local fallback. Provide a distinct hosted bootstrap/migration procedure that operates only on application-owned objects. Supabase does not grant customers unrestricted superuser access; its managed roles and ownership must be inspected instead of assuming the local bootstrap script can run there. Never alter the provider's `auth` schema. [Supabase role limitations](https://supabase.com/docs/guides/database/postgres/roles-superuser).

For a persistent Python process, evaluate the direct database route first; use the shared session pooler if the selected network requires IPv4. Record actual endpoints from the project. Start with existing small bounded application pools; account for both runtime/authentication roles and separate migration sessions. Transaction pooling requires its own prepared-statement, transaction-local owner context, session cleanup, and migration tests. It is not the current default. [Connection guidance](https://supabase.com/docs/guides/database/connecting-to-postgres).

## Evidence checklist

All hosted rows below are **not run**. Record dated, sanitized results and the tested application revision locally; never put connection strings, certificates with private keys, bearer tokens, owner identifiers, or raw provider responses in a PR.

| Area | Required evidence | Current state |
| --- | --- | --- |
| Project and cost | Dedicated non-production project, chosen region, actual PostgreSQL version/extensions, account MFA, plan quotas, pausing behavior, database connections, SMTP and recovery email availability | Not configured; verify free-plan compatibility without silently enabling paid features |
| Database route | Known project hostname and expected role/database; direct or session pooler selected; IP family tested from the future application host; bounded connection acquisition/outage behavior | Hosted adapter unimplemented |
| TLS | `sslmode=verify-full` with the correct trusted CA; expected hostname succeeds; wrong hostname, untrusted CA, and plaintext fail; enable/verify server SSL enforcement on the selected route | Not run |
| Network denial | Only intended source addresses reach direct and pooled endpoints; a genuinely unauthorized source is denied; private/gated application entry and host firewall verified | Not run |
| Credentials | Separate runtime/auth/migrator/backup duties; startup reads private files; no elevated database/service-role key in normal API or browser; permission failure and rotation tested | Local TLS file mounts only; hosted credential injection unimplemented |
| Ownership and grants | Runtime is not a table owner, superuser, role administrator, or RLS bypass role; authentication role cannot read preferences; runtime cannot read identity/session state; every private table forces RLS; inspect inherited/default privileges and functions | Local role/RLS tests pass; managed-role compatibility not run |
| Managed APIs | Application schemas excluded from exposed schemas; unused Data API disabled; `PUBLIC`, `anon`, `authenticated`, `service_role`, and default object grants inspected; negative REST/function access tested | Not run |
| Migrations | Fresh/upgrade migration and failure rollback through a dedicated role; target revision checked; no automatic migration on API startup; no edits to managed schemas | Local migration checks cover the [current application head](development.md#local-postgresql); hosted procedure unimplemented |
| Connection reuse | Two-owner read/write denial, missing identity, commit/rollback/cancellation, reconnect, pool exhaustion and stale context through the actual chosen route | Local direct PostgreSQL passes; hosted route not run |
| Authentication | Disabled public/anonymous signup and unused providers; pre-enrolled owner mapping; correct JWT issuer/audience/key rotation; password/TOTP, secondary factor, recovery email, refresh rotation, revocation, and outage tests | Synthetic provider contract tests pass; hosted checks not run |
| Browser and proxy | Real HTTPS origin, secure `__Host-` cookies, exact Origin/CSRF, no cache, redirects, proxy trust and header limits; session clearing after expiry/logout | Local shell/proxy and synthetic cookie tests pass; packaged authenticated path not configured |
| Recovery | Encrypted representative backup, off-site object/key recovery, compatible role reconstruction, zero revived sessions, independent provider identity recovery, new-secret rotation, measured data loss/time | Synthetic local [financial recovery](local-packaging.md#encrypted-foundation-recovery) is implemented; hosted and provider-identity recovery not run |
| Image and host | OS image vulnerability review, signed release provenance, private registry process if used, patching, protected disk/swap, core dumps, resource/import limits and monitoring on the actual AMD host | Local non-root limits measured; release/host checks not run |

Server SSL enforcement supplements client hostname/CA verification; retain both. Database address restrictions cover database/pooler routes and do not replace authentication or protect every HTTP service. [SSL enforcement](https://supabase.com/docs/guides/platform/ssl-enforcement), [network restrictions](https://supabase.com/docs/guides/platform/network-restrictions).

Private application tables need both correct grants and RLS. Inspect actual project defaults rather than relying on the provider's evolving defaults, and check function execution as well as table access. [Supabase API security](https://supabase.com/docs/guides/api/securing-your-api).

## Recovery and release boundaries

The [local recovery format](local-packaging.md#encrypted-foundation-recovery) covers its explicit durable application-record manifest, including financial evidence, in disposable PostgreSQL. It cannot restore Supabase Auth users/factors or external storage objects. Reconstructing a mapping is not proof that the corresponding provider identity remains trustworthy. Define the independent provider recovery/revocation procedure before using a real identity.

Select off-site storage, independently protected encryption keys, deletion protection, retention, export budget, and failure alerts. The provisional objectives remain a 24-hour recovery point and one-day restoration, subject to actual tests. Supabase recommends regular exports/off-site copies for Free projects; provider backup coverage and storage object recovery must be checked separately. [Provider backup guidance](https://supabase.com/docs/guides/platform/backups).

Do not treat a successful checklist review as a deployment. A hosted release needs an implemented hosted adapter, dedicated test evidence, a versioned release, recoverable migration, verified entry point, and monitored operation. [Operations plan](operations.md) contains the remaining host and incident-response work.
