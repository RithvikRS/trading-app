# Step 3E.1: Supabase authentication and restricted enrollment

The server-side authentication service now verifies a Supabase password sign-in, requires authenticator-app TOTP, and resolves only explicitly provisioned identities. It is exercised by local tests and an interactive development walkthrough. No Supabase project is configured, and no hosted smoke test has run. This document records the server-only Step 3E.1 service. [Step 3E.2](browser-sessions.md) now adds opt-in HTTP authentication, browser sessions, and recovery; the protected UI remains separate future work. An internal MFA result does not grant browser or workspace access.

## Integration decisions

| Decision | Implementation |
| --- | --- |
| Provider and factors | Supabase Auth; confirmed email/password followed by mandatory TOTP. The TOTP API is free according to the provider documentation checked on 23 October 2026 |
| Protocol libraries | Documented Supabase Auth REST operations using HTTPX2 2.16.0; PyJWT 2.15.1 with locked cryptography dependencies verifies signatures. No custom password, TOTP, signing, or encryption algorithm |
| Runtime credential | A publishable key only. Secret/service-role keys and legacy JWT API keys are rejected |
| Destination | Exactly one canonical HTTPS `<project-ref>.supabase.co` origin; fixed `/auth/v1` issuer. No custom URL, plaintext, proxy-environment override, redirect following, or caller-supplied key URL |
| Token verification | ES256/P-256 or RS256 public signing keys from the configured issuer's JWKS. Validate signature, exact issuer/audience, required claims, subject/session UUIDs, role, assurance level, and fresh password/TOTP methods |
| Token custody | Memory only for the short attempt; redacted representations, no browser tokens, disk persistence, background refresh, or session handoff |
| Development identity | Deterministic provider responses and generated signing keys under tests; real local PostgreSQL for mapping/grant checks. No environment setting can enable a fake identity |

References: [Supabase TOTP](https://supabase.com/docs/guides/auth/auth-mfa/totp), [Auth REST contract](https://github.com/supabase/auth/blob/master/openapi.yaml), [JWT signing keys](https://supabase.com/docs/guides/auth/signing-keys), [PyJWT verification](https://pyjwt.readthedocs.io/en/stable/usage.html).

The adapter uses explicit operations instead of a shared stateful authentication client. Every operation receives the attempt's own token; there is no shared current user, SDK token storage, refresh timer, or implicit registration path. Keys are fetched for each verification, with no stale-key fallback. A key-service outage denies authentication. Provider calls use verified TLS, four maximum connections, a three-second connect limit, two-second pool wait, five-second read/write limits, and a ten-second streaming-response budget checked between chunks. A blocked read can additionally last until its read timeout. Responses are limited to 64 KiB and reject compressed bodies, unexpected content types, redirects, and malformed structures.

## Authentication flow

1. Apply bounded admission before sending the password. Check the provider's settings: signup disabled, confirmed email required, email sign-in enabled, and anonymous/social/phone/SAML/passkey paths disabled. Configuration drift blocks login rather than modifying the provider remotely.
2. Obtain the password token and independently verify its signed claims. Require `aal1`, `authenticated`, a non-anonymous user, an exact `authenticated` audience, and a password method within five minutes. Tokens must be unexpired, recently issued, and valid for at most one hour. No email or mutable profile claim chooses an owner.
3. Resolve the exact verified `(issuer, subject)` through `trading_auth`, a separate restricted database role. Unknown or inactive identities fail without creating any owner. The provider's user endpoint confirms the subject, confirmed-email status, and current factor list.
4. Select an existing verified TOTP factor. Only a newly provisioned identity with no factors and an unset enrollment marker can start first enrollment. Return the bounded setup key once; provider SVG and links are discarded. Existing unverified or unsupported factors block automatic enrollment.
5. Bind each challenge to the factor selected inside that attempt. Verify a six-digit code, then verify the returned token's signature, `aal2`, fresh password/TOTP methods, and unchanged subject/session. Recheck the provider's verified factor and the local active identity before returning an internal result. Partial authentication cannot produce that result.
6. Persist the enrollment marker and close the attempt. The walkthrough discards its provider session with `scope=local` and creates no application session. Local token references are dropped even when cleanup fails; failed cleanup is reported and does not restore the attempt. Provider access JWTs can remain valid until expiry, so this cleanup is not a claim of immediate JWT revocation.

Attempts expire five minutes after password processing begins and do not extend on activity. An attempt allows at most five code submissions and one operation at a time. The service permits four simultaneous attempts, one per resolved owner, five starts per normalized email in five minutes, and thirty starts globally in that window. Invalid credentials and abandoned attempts count. Email rate keys are keyed hashes with a random process-local key; raw emails are not stored in the limiter.

These admission controls are process-local and reset on restart. They are not a distributed or durable login throttle. [Step 3E.2](browser-sessions.md) uses a separate durable PostgreSQL admission boundary for browser authentication. No HTTP routes exist here, so CSRF/cookies are not partially introduced. Reuse one service instance when integrating it; recreating it per request would reset its counters. No external provider call holds a database transaction open.

## Identity and enrollment database boundary

Revision `0003_auth_identity_lookup` follows the unchanged ownership revision. `python scripts/database.py up` adds one independent `trading_auth` credential without rotating the existing three passwords; `migrate` applies the new grants and policies.

The identity role can read only active owner IDs/status and the minimal identity mapping columns. It can set `mfa_enrolled` to true for an active mapped owner. RLS rejects setting it back to false. It cannot insert/delete mappings, change subjects or ownership, activate owners, access preferences or migration metadata, create objects, or assume runtime/migrator roles. Workspace runtime still cannot read identity mappings. Privilege drift, database outages, or a disabled mapping fail closed. This role is trusted to resolve already-verified identities; arbitrary SQL with its credentials could enumerate those minimal mappings.

The separate administrative `provision-owner` command creates a new internal owner and exact issuer/subject mapping in one transaction. Duplicate identities fail atomically; there is no upsert, relinking, reactivation, or MFA reset. It accepts only the managed local database's bootstrap identity and checks the server marker. Normal authentication never loads that credential. The administrator must establish the intended provider account separately; entering a UUID does not verify who controls it.

Once an identity has completed MFA, loss of its provider factor requires recovery. Password knowledge alone cannot clear the marker and enroll a replacement through this service. Cancelling first enrollment can leave an unverified provider factor; it is not silently deleted or replaced. The [browser-session runbook](browser-sessions.md#recovery-procedures) describes the implemented backup factor, replacement, email recovery, and abandoned-enrollment controls. This original command-line service creates no browser session.

## Local verification and migration

From the repository root:

```powershell
python scripts/database.py up
python scripts/database.py migrate
python scripts/database.py status
python scripts/checks.py all
```

The Step 3E.1 revision is `0003_auth_identity_lookup`; the current head is `0008_import_staging`. Ordinary tests require no Supabase credentials, internet identity calls, paid service, real owner, or real MFA seed. Provider responses/signing keys stay in test modules; the database runner uses its guarded disposable cluster. The historical 3C/3D tests target their original revisions; new tests exercise the current head and both restricted roles.

Upgrade preserves existing owner mappings and preferences. New enrollment markers default to false; no owners are seeded by migration. The local service adds its new credential only when the original set is complete. Failed migrations roll back DDL and version metadata together. Test-only downgrade removes auth grants and the marker; re-upgrade cannot reconstruct the old marker. Consequently downgrade is not a recovery method for used identities. Development recovery uses a forward migration, and shared migrations must not be rewritten.

Tests cover signed-but-invalid claims, tampering, wrong issuer/audience/role, key rotation and outage, unknown/inactive identities, cross-owner denial, initial enrollment, wrong codes, unsupported/missing factors, deadlines, cancellation, concurrent attempts, admission limits, safe diagnostics, and role restrictions. Local validation and actual GitHub runs are recorded separately.

Historical Step 3E.1 Windows evidence on 24 October 2026: the complete shared check passed, followed by passing backend/database checks for the final additional assertions. Final totals are 15 verification-helper tests, 189 API/authentication/unit tests, 100 PostgreSQL tests, and 478 frontend tests. Ruff, strict mypy, frontend types/build, workflow policy/actionlint, documentation links, and repository secret scans passed. Python and npm audits reported no known vulnerabilities. Development reached `0003_auth_identity_lookup`, retained its original credentials, and had no owner, identity, or preference rows. GitHub CI results are recorded in the PR.

## Optional provider walkthrough — not run

A later manual smoke test needs a dedicated Free development project and a fabricated account. Configure closed registration, confirmed email, TOTP, asymmetric JWT signing, and an access-token lifetime of at most one hour. Disable other sign-in methods. The application validates the exposed settings but does not configure the project, SMTP, entitlement, or administrator access. Set up cloud-administrator MFA separately. Do not use production credentials or a personal financial identity.

The authentication tools read `TRADING_AUTH_PROJECT_URL` and `TRADING_AUTH_PUBLISHABLE_KEY` explicitly from the process environment. Step 3E.2 adds the separately default-off `TRADING_AUTH_RECOVERY_EMAIL_ENABLED` control. No dotenv file is loaded, and no admin API key is accepted. Supply the actual canonical project URL and publishable key locally; never put passwords, codes, or tokens in command arguments or repository files. The normal API defaults remain liveness-only; browser authentication requires its explicit enable setting and private key.

After the development database is upgraded, use a private interactive terminal:

```powershell
python scripts/authentication.py provision-owner
python scripts/authentication.py smoke
```

Provisioning prompts for the provider user UUID. The smoke command prompts without echo for email, password, and TOTP. First enrollment displays its setup key only in an interactive terminal; it refuses redirected input/output. Add that key manually to an authenticator using TOTP with six digits and a thirty-second interval. Do not record or share that terminal or its scrollback. The application writes no seed file and does not display provider tokens. The command confirms completion only after provider-session cleanup succeeds; it opens no workspace.

Record actual provider/version/configuration evidence, closed signup, first enrollment, repeat sign-in, wrong-code rejection, and outage behavior when this walkthrough is run. Hosted key behavior, email delivery, provider revocation, MFA recovery, Supabase database TLS/pooling, and Oracle deployment remain unverified. [Step 3E.2](browser-sessions.md) implements browser/session transport, revocation, recovery, and security events with local evidence; [Step 3F.1](protected-workspace.md) adds the separate protected shell, and [Step 3F.2](display-preferences.md) adds authenticated preferences. The fictional prototype remains separate.
