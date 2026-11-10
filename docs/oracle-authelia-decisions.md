# Oracle Database and Authelia: decisions and implementation handoff

Decision date: 5 November 2026.

## Status and scope

The owner has selected Oracle Database and the existing Authelia identity service as the new target direction. Rewriting database and authentication integrations is acceptable. Implement the trading app after the shared infrastructure, recovery, monitoring, and identity work in the separate portfolio repository.

This document changes the planned target, not the current implementation. Existing code and tests still use PostgreSQL and Supabase-specific authentication. No database conversion, identity migration, infrastructure provisioning, credential change, or production deployment accompanies this document.

For future implementation, this decision supersedes the Supabase hosting/authentication selection in [architecture](architecture.md) and [authentication options](authentication-options.md). Their implementation details remain evidence of the current system. Update those documents alongside the actual migration rather than claiming the new integrations already work.

The [10 November compatibility review and migration sequence](oracle-authelia-migration.md) records the current repository inventory, updated shared prerequisites and unperformed acceptance checks.

## Selected direction

| Area | Target |
| --- | --- |
| Frontend | Keep React/TypeScript/Vite and the protected same-origin workspace |
| API | Keep Python/FastAPI unless a separate reviewed decision changes it |
| Hosted database | Oracle Autonomous Database, targeting the Always Free offering if the actual tenancy and feature requirements fit |
| Identity | Existing self-hosted Authelia through native OpenID Connect, with MFA |
| App sessions | Preserve application-controlled opaque server-side sessions and explicit revocation |
| Ownership | Internal owner identities mapped to verified OIDC issuer/subject; enforce isolation in API and database |
| App hosting | Ampere A1 worker in the existing three-node Swarm; HTTPS through Caddy on AMD node 1 |
| Releases | Own application image, deployment lifecycle, migrations, and recovery boundary |

Do not replace Supabase Auth with only a Caddy forward-auth rule. Do not substitute Oracle for the PostgreSQL dependencies of unrelated packaged applications such as Rakazo.

## Infrastructure context

AMD node 1 remains Swarm manager, public ingress, and host for existing portfolio state. AMD node 2 remains a worker; monitoring is now documented as configured in the portfolio repository. This repository review does not establish completed runtime/outage acceptance. Ampere A1 is a worker with `workload.compute=true`, 4 OCPUs and 24 GB RAM. Swarm reports its architecture as `aarch64`; container images target `linux/arm64`.

The portfolio catalog now supports approved worker storage with exact-node placement and coordinated backup guards. Trading-specific paths, ownership and recovery coverage still need to be registered and tested before using worker-local files. A managed Oracle database does not remove the need to back up private statement files, encryption keys, and other non-database state.

The current local Compose package is a rehearsal, including loopback-only access and `network_mode: service:gateway`. Design a hosted Swarm configuration separately. Do not directly deploy that Compose file or expose the API/database to bypass its current assumptions. Avoid placing the app in another repository's stack where `docker stack deploy --prune` could remove it.

## Oracle migration work

1. Inventory PostgreSQL-specific SQL, drivers, types, defaults, identity/sequence behavior, constraints, functions, policies, grants, and migration scripts. Confirm Oracle support for the required features and chosen free service.
2. Choose a supported Python driver and SQLAlchemy dialect, validate ARM/Python compatibility, and test certificate-verified connectivity. Use distinct bootstrap/migrator/runtime/identity responsibilities with least privilege.
3. Define the development and CI database strategy. Use real Oracle integration tests; PostgreSQL or SQLite tests cannot establish Oracle semantics. Do not require production credentials for CI.
4. Port exact financial types and serialization without float conversion. Preserve native amounts/currencies, dates, explicit unknown values, immutable source evidence, and the separation of historical observations from current valuations.
5. Reimplement owner-context enforcement. PostgreSQL RLS and `SET LOCAL` semantics do not transfer automatically. Evaluate Oracle application contexts and database policy mechanisms against actual service support, then document and test the selected design. Never silently reduce isolation to optional query filters.
6. Rework pooled connection cleanup, rollback, cancellation, deadlines, locking, concurrency, idempotent replay, and transaction ordering. A reused connection must not retain a prior owner's authority, including after errors or cancellation.
7. Define migration and recovery paths using synthetic fixtures first. Keep historical migrations intact; introduce a deliberate Oracle baseline/transition rather than rewriting applied migration history.

Before migration, inspect whether any private data or provisioned identities need preservation. Do not assume the repository's fixtures describe all existing environments. Take and verify backups before changing a populated database.

## Authelia OIDC integration

Use a maintained OIDC client implementation with authorization code flow and PKCE. Register a dedicated client, exact HTTPS callbacks, and only required scopes. Keep client secrets server-side and outside Git. Configure MFA for this client and verify the selected Authelia release's assurance claims and behavior.

The browser signs in at Authelia; the API verifies the callback and creates its own opaque session. Validate state, nonce, signature, issuer, audience, expiry, and the required authentication assurance. Do not interpret a Supabase-specific `aal2` claim as an Authelia contract. Map verified `(issuer, subject)` to the internal owner; email, display names, request parameters, and forged proxy headers cannot choose ownership.

Keep closed/explicit enrollment initially. Do not add public registration, family sharing, or automatic ownership reassignment as a side effect of SSO. The infrastructure's family/friend accounts do not automatically receive financial-app access.

Preserve secure/HttpOnly cookie policy, CSRF defenses, short-lived admission state, callback replay protection, session expiry, logout, revocation, durable abuse controls, and the session-context boundary used by frontend requests. Define fresh-authentication requirements for sensitive operations and recovery. Test identity-provider outage, key rotation, disabled users, changed groups, expired MFA assurance, and an active app session after the identity account is disabled.

Authelia authenticates users. The application still authorizes every financial operation. Disabling an IdP account is not sufficient evidence that existing app sessions have been revoked. Keep an independent recovery procedure for the identity service and the application's encryption material.

## Preserve these existing contracts

Use the current implementation and tests as the source for behavioral requirements:

- [Ownership isolation](ownership-isolation.md): cross-owner denial, restricted roles, pooled-context cleanup.
- [Authentication foundation](authentication-foundation.md): explicit enrollment, MFA, verified identities, safe diagnostics.
- [Browser sessions](browser-sessions.md): opaque sessions, revocation, recovery, and browser security.
- [Architecture](architecture.md): exact evidence, limited provider access, API-only financial access.
- [Local packaging and recovery](local-packaging.md): encrypted recovery and separate migration identities.

Preserve frontend masking, stale/partial-data behavior, exact monetary values, historical evidence, and explicit unsupported states. Do not enable live acquisitions, financial writes to external providers, or real accounts merely to validate a new deployment.

## Suggested implementation increments

| Increment | Deliverable | Acceptance gate |
| --- | --- | --- |
| 1. Compatibility and design | Oracle feature matrix, identity mapping, hosted topology, migration inventory | Resolve unsupported free-tier features and document substitutes before porting |
| 2. Oracle foundation | Driver, schema baseline, role provisioning, owner-scoped transaction layer | Real Oracle tests prove cross-owner denial and cleanup after errors/cancellation |
| 3. Authelia integration | OIDC login, enrollment, MFA assurance, app sessions | Two synthetic users remain isolated; invalid/replayed callbacks and incomplete MFA fail closed |
| 4. Vertical slice | One authenticated account/preference flow through Oracle | End-to-end tests pass without weakening existing security contracts |
| 5. Domain migration | Financial persistence and remaining workflows | Precision, evidence, replay, concurrency, and ownership regression tests pass |
| 6. Hosted staging | ARM image, Caddy/Swarm configuration, bounded runtime resources | Synthetic-only deployment, health checks, migrations, and recovery rehearsal pass |
| 7. Production readiness | Reviewed configuration, backup schedule, operational runbook | Explicit cutover decision after staged restore and access tests |

Keep code changes local for review unless the owner separately authorizes pushing, merging, or deployment. This handoff is not permission to create paid Oracle services, modify the production identity provider, delete data, or run production migrations.

## Monitoring and recovery acceptance

Expose safe liveness and dependency-readiness checks. Add worker heartbeat and source-freshness signals as those features become active. Avoid financial records, credentials, and personal identifiers in monitor responses and logs. Configure alerts through the shared monitoring plan, including an independent path for a node-1 outage.

Test encrypted database exports and restoration, file/key recovery, and session invalidation after restore. Do not assume container-image rollback reverses a schema or data migration. Document compatibility between releases and migrations, and keep recovery copies outside the tenancy.

## Open implementation decisions

- Exact Oracle service, supported feature set, region capacity, connection method, and free-tier limits.
- Local/CI Oracle environment and driver/platform compatibility.
- Oracle owner-isolation mechanism and restricted-role implementation.
- Authelia client policy, MFA assurance verification, session lifetimes, offboarding, and identity migration.
- Stable application hostname, storage for statements, deployment ownership, and migration execution procedure.
- Any future shared financial workspace permissions; these are outside this infrastructure decision.

Do not present these choices as already implemented. Update the main architecture, authentication, development, security, and recovery documentation when the corresponding code changes land.

## References

- [Oracle Always Free Autonomous Database](https://docs.oracle.com/en-us/iaas/autonomous-database-serverless/doc/autonomous-always-free.html): review current resource, inactivity, and service restrictions.
- [OCI managed PostgreSQL pricing](https://www.oracle.com/cloud/postgresql/pricing/): this is a different paid product, not the selected free Oracle Database direction.
- [Authelia OIDC integration](https://www.authelia.com/integration/openid-connect/introduction/).
- [Authelia OIDC provider configuration](https://www.authelia.com/configuration/identity-providers/openid-connect/provider/).
