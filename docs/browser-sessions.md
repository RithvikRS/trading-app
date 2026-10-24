# Step 3E.2: Browser sessions, revocation, and recovery

The Python API now has opt-in browser authentication using Supabase password/TOTP verification and local PostgreSQL session state. Security decisions remain on the server. The fictional frontend is unchanged; [Step 3F.1](protected-workspace.md) adds the protected UI and [Step 3F.2](display-preferences.md) adds authenticated preference persistence. Preference access refreshes the session without extending idle expiry, then uses a short guard across runtime commit to order saves against application revocation. No hosted project, real identity, financial record, or deployment was used for this increment.

## Session and credential boundary

The browser receives a cryptographically random 256-bit opaque session cookie. PostgreSQL stores its SHA-256 verifier, an unrelated audit reference, the internal owner mapping, deadlines, and encrypted provider state. `cryptography` AES-256-GCM authenticates the ciphertext and its row verifier; a random 96-bit nonce is generated for every write. Swapping ciphertext between rows or changing the key fails closed. Passwords, submitted codes, and enrollment seeds are never persisted. Access/refresh tokens never appear in browser responses, local storage, URLs, frontend bundles, or security events.

The local key lives in the separately protected, ignored `.cache/auth/session.key` file, outside PostgreSQL and database backups. Initialization is explicit and refuses to overwrite an existing file. Windows directory ACLs restrict access to the current user and SYSTEM; Unix permissions are private. Protect the workstation account and disk too: an application process or machine compromise can read decrypted state. Hosted key injection, encrypted swap, crash-dump controls, and backup custody remain Step 3G work.

| Control | Implemented behavior |
| --- | --- |
| Partial sign-in/recovery | Five minutes from admission; no workspace access; a failed MFA operation consumes that attempt and requires a new sign-in |
| Active session | Fifteen-minute idle limit and eight-hour absolute limit, both checked in PostgreSQL |
| Fresh authentication | Five minutes from the original password admission; renewal and completing MFA do not reset this clock |
| Activity | Only explicit `POST /session/activity` extends idle time. Status checks and provider refresh do not. The future UI must call it for real user activity, never a polling timer |
| Cookie rotation | New identifier at password start, MFA completion, and entering backup enrollment; the old verifier is no longer accepted |
| Normal renewal | Retains the opaque cookie while rotating provider credentials on the server; cannot extend absolute expiry or authentication freshness |
| Errors/outages | Generic JSON and no-store headers. Required database/identity/provider checks fail closed; uncertain refresh or failed MFA consumes local state |
| Hosted transport | Tested cookie policy uses `__Host-` names, `Secure`, `HttpOnly`, `SameSite=Strict`, `Path=/`, and no Domain. Hosted startup is still unsupported |
| Local transport | Separately named `trading_dev_session`, HttpOnly and Strict, for exact IPv4 loopback HTTP only. This relaxation cannot be selected for a remote host |

Every active-session check refreshes with Supabase, verifies signed AAL2 claims and unchanged issuer/subject/provider-session identity, and confirms that the authenticator used for this session still exists. This deliberately prefers current provider state over offline availability. It adds provider latency and consumes Auth requests; the protected UI should avoid unnecessary polling. Supabase access JWTs alone cannot prove immediate provider logout. [Supabase sessions](https://supabase.com/docs/guides/auth/sessions), [sign-out behavior](https://supabase.com/docs/guides/auth/signout).

A short database transaction claims a 90-second exclusive lease before provider I/O, then commits. A competing request gets 429 instead of reusing a refresh token. Finishing checks the same lease, live owner mapping, and deadlines before storing the rotated token. A crashed/expired lease is discarded; an uncertain exchange is never automatically replayed. Logout can interrupt a lease. Revocation and completion serialize, so an in-flight refresh cannot resurrect deleted state. No provider request holds a database transaction open.

## HTTP contract

Routes exist only when authentication is explicitly enabled. They share `/api/v1/auth`. All inputs are allowlisted Pydantic objects; unknown fields are rejected. Unsafe requests require `Content-Type: application/json`, a matching signed `X-CSRFToken` header/cookie, and the exact configured Origin. Requests are limited to 4 KiB, including chunked bodies, with a five-second body-read deadline. Query parameters, bearer authorization, duplicate authentication headers/cookies, and cross-site/sibling-origin browser requests are rejected.

`starlette-csrf` supplies signed double-submit CSRF verification. The sign-in state additionally binds the CSRF value to that browser session. SameSite supplements these checks. There is no CORS opt-in, wildcard origin, redirect callback, token exchange URL, or return-to parameter. `GET /bootstrap` establishes the readable CSRF cookie; send its value as `X-CSRFToken` on session checks as well as mutations. Authentication cookies remain HttpOnly. [CSRF middleware](https://github.com/frankie567/starlette-csrf), [OWASP guidance](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html).

| Method and route | Input / result |
| --- | --- |
| `GET /bootstrap` | Establish CSRF cookie; status and recovery-email capability only; no identity or session granted |
| `POST /login` | Email/password → restricted MFA cookie and eligible factor IDs; first enrollment may return its setup key once |
| `POST /mfa/verify` | Factor ID/code bound to that attempt → rotated active cookie, or restricted password-recovery cookie |
| `GET /session` | Active session status, deadlines, verified/unverified TOTP IDs; never slides idle expiry |
| `POST /session/activity` | Empty object; active session check plus explicit idle extension |
| `POST /logout` | Empty object; revoke this local session, clear cookie, attempt provider-local logout |
| `POST /revoke-all` | Empty object; active local session required; revoke all owner sessions before provider-global logout |
| `POST /recovery/request` | Email → generic 202 after provider request; unknown/disabled account responses are indistinguishable |
| `POST /recovery/verify` | Email and 6–10 digit email code → restricted MFA attempt for an already enrolled mapped owner |
| `POST /recovery/password` | Restricted recovery cookie and a 16–128 character new password; revoke all, change password, require full sign-in |
| `POST /mfa/backup` | Fresh active session and empty object → restricted setup cookie, factor ID, and one-time setup-key display |
| `POST /mfa/backup/verify` | Restricted setup cookie/code → verify second factor, revoke all, require full sign-in |
| `POST /mfa/remove` | Fresh session and factor ID; retain the verified factor used for this sign-in, revoke all, require full sign-in |

Status 401 clears the browser session cookie. Status 503 indicates unavailable authentication; no cached identity or demo data may substitute. A concurrent operation returns 429 with a short retry hint. Admission exhaustion also returns 429; the actual rolling window remains authoritative. Auth mutations must not be blindly retried after an uncertain response. A lost successful response can leave an unusable server record until expiry, but cannot expose its cookie or credentials.

## Admission and database privileges

Revision `0004_browser_sessions` adds `auth_sessions`, `auth_revocations`, `auth_admissions`, and `security_events` inside the private `app` schema. All four enable and force RLS. The existing `trading_auth` role receives only its security-registry operations; it cannot access workspace preferences, provision identities, change ownership, run DDL, bypass RLS, or truncate tables. Workspace runtime cannot read or write the security registry. The authentication role is trusted across owners for security lookup; possession of its SQL credentials is not an owner-scoped interface.

Admission is atomic and restart-safe: five starts per normalized email and thirty globally in a rolling five-minute window, including failed and abandoned login/recovery attempts. Only keyed hashes of normalized emails are stored. The durable global limit also bounds distinct-email entries. Four sign-in operations can run concurrently in the process. Expired admissions and session ciphertext are pruned on admission. Database credentials and admission state do not change on application restart.

Revoke-all records an owner cutoff as well as deleting existing sessions. A login admitted before that cutoff cannot finish afterward. Credential mutations validate their live operation lease and revoke local sessions before making the provider change. Database or event-write failure rolls back the corresponding local state transition. An upstream timeout may mean that a password/factor operation succeeded remotely; restart the explicit recovery/sign-in flow instead of inferring success or restoring old state.

Security events contain an allowlisted event/outcome, database UTC time, generated request correlation ID, and optional opaque actor/audit references. No email, IP, user agent, provider session ID, cookie, verifier, token, secret, code, request body, or financial field is recorded. The authentication role can append/read events but cannot update/delete them. Boundary rejections also retain the existing sanitized request/status log. There is no event export or telemetry integration.

Event semantics follow the authentication stage: `login` success means a password accepted into a restricted attempt, and `recovery_verify` success means an email code accepted into a restricted attempt. Neither grants workspace access. A subsequent `mfa` event shares that attempt's non-secret audit reference; recovery still requires the separate password operation and normal sign-in.

Keep security events for 30 days during development; retention deletion is an explicit administrator operation, not an application privilege. Future operational maintenance must prune old events and expired idle systems, monitor table size, and coordinate backup retention. Revocation cutoffs must survive at least the maximum admitted-operation window; normal application code does not delete them. Do not include these security tables in browser/Data API exposure.

## Recovery procedures

**Lost primary authenticator:** register and verify a second TOTP factor on a separate device or protected recovery store while the primary still works. Sign in with the password and backup factor, then remove the lost primary using fresh authentication. The factor proving the current sign-in cannot remove itself. A last verified factor cannot be removed. Adding/removing factors revokes local sessions and requires another password/TOTP sign-in. Provider-global cleanup is attempted separately.

**Forgotten password:** request an email recovery code, verify it in the same browser, and complete an existing verified TOTP challenge. The resulting cookie can only change the password; it never becomes an active workspace session. MFA success revokes other local sessions, and the password operation revokes all again before the provider change. Completion requires normal sign-in. Email possession alone cannot enroll a replacement authenticator or reset the enrollment marker.

Email recovery defaults off. Before setting `TRADING_AUTH_RECOVERY_EMAIL_ENABLED=true`, configure and test the dedicated development project's recovery email template to show only `{{ .Token }}` as a code, without a confirmation URL or access token. Configure a short code expiry and a working sender. The server submits `/verify` with `type=recovery`; it accepts no URL token/callback. A configuration flag is an operator assertion, not proof of SMTP delivery or template correctness. Hosted SMTP limits and any sender cost must be checked separately. [Email templates](https://supabase.com/docs/guides/auth/auth-email-templates), [Auth REST contract](https://github.com/supabase/auth/blob/master/openapi.yaml).

**Abandoned enrollment:** a newly provisioned, never-enrolled owner can resume the sole existing unverified TOTP with the setup key already displayed. The application never reveals that seed again. After an established sign-in, a fresh verified factor can remove an abandoned, unverified backup factor before starting again. A failed challenge consumes the local attempt; retry through password sign-in. A permanent MFA marker prevents turning missing factors into first enrollment.

**All factors or the initial setup key lost:** fail closed. Use separately protected provider-administrator access to verify the intended account and revoke provider sessions. Revoke local sessions using the administrative command below. Removing an unverified first-enrollment factor through the provider console can recover a never-enrolled account; the application does not reset the permanent marker for established identities. Restoring an established identity after total factor loss needs a separately designed/tested administrative recovery procedure; no self-service bypass or claim of recovery coverage is made here. Back up the authenticator before relying on it. Experimental provider recovery codes are not enabled.

**Provider outage or suspected compromise:** application revoke-all succeeds locally even when provider logout fails, and reports provider cleanup as unavailable. With no usable browser session, run `python scripts/authentication.py revoke-owner` in a private terminal and enter the exact mapped provider UUID. It uses only the local administrative database path, works for disabled owners, records the revocation, and never clears MFA, activates owners, or modifies preferences. Revoke provider sessions separately once administrator access is available. Expiry/pruning does not guarantee upstream session deletion. Provider JWTs may remain valid until their own expiry.

**Key loss or restore:** stop the API, administratively revoke local sessions, replace the private key explicitly, and require full sign-in. Never automatically generate a replacement during startup or restore encrypted sessions into service. Preserve the global admission window; wait out its five minutes before restarting after intentional key rotation. Restore keys through separate custody, never alongside a database dump. Local key rotation discards sessions rather than re-encrypting long-lived tokens. The hosted key/backup drill remains unrun.

## Local setup and verification

Ordinary tests require no Supabase configuration. To prepare a later dedicated development project:

```powershell
python scripts/database.py up
python scripts/database.py migrate
python scripts/authentication.py init-session-key
```

Expected head: `0004_browser_sessions`. Upgrade preserves owners, mappings, enrollment markers, and preferences and seeds no identities. Existing migrations remain unchanged. Downgrades are restricted to disposable tests; dropping these tables loses sessions, revocation cutoffs, admission history, and security events. Use forward repairs for a used database.

Supply `TRADING_AUTH_PROJECT_URL` and `TRADING_AUTH_PUBLISHABLE_KEY` locally using the [provider runbook](authentication-foundation.md), then set `TRADING_API_AUTH_ENABLED=true` for the documented Python entry point. Startup refuses missing/invalid provider configuration or session keys. The entry point still binds only `127.0.0.1`; its browser Origin is exactly `http://127.0.0.1:<TRADING_API_PORT>`. The separate Vite prototype is not connected and no cross-origin exception is added. [Step 3F.1](protected-workspace.md) serves a separate protected build directly at this API origin when enabled. Recovery remains off until its explicit setup above is completed. No secret-bearing command arguments or dotenv discovery are used.

Run `python scripts/checks.py all`. The new tests use generated signing keys, the actual provider adapter, signed CSRF middleware, API requests, and real disposable PostgreSQL. They cover ciphertext/context tampering, fixation, restart, idle/absolute expiry, original authentication freshness, concurrent refresh, logout during renewal, revocation races, admission limits, partial/recovery denial, backup/replacement/abandoned factors, provider and key outages, cross-owner relabeling, event redaction/grants, and migration rollback. The historical suites continue to exercise their original migrations.

Local Windows evidence on 24 October 2026: all four shared check groups passed. Final totals are 15 verification-helper tests, 219 backend tests, 138 PostgreSQL tests, and 478 frontend tests. Ruff, formatting, strict mypy, frontend types/build, workflow policy/actionlint, documentation links, and secret scans passed. Python/npm audits reported no known vulnerabilities. Development reached `0004_browser_sessions`; all seven application tables remained empty. The frontend retains its existing canvas-test and bundle-size warnings. Actual GitHub CI results are recorded separately in the PR.

Hosted password/MFA, recovery email delivery and replay, actual refresh rotation/reuse detection, remote logout, real factor changes, and hosted TLS/keys remain **not run**. Local browser UI evidence is recorded separately in [Step 3F.1](protected-workspace.md). No Supabase project exists yet. Before hosted use, repeat these contracts against a fabricated account, exercise the backup authenticator and recovery flow end to end, inspect redacted provider evidence, and verify current plan entitlements. Local provider doubles establish application behavior, not the behavior or configuration of a live service.

## Financial identity reads

[Step 4G.1](financial-reads.md) extends the same browser protections to `/api/v1/finance`. Read-only JSON queries require active MFA and bound CSRF, preserve the idle deadline and validate session/owner state after constructing their bounded response. Database-query unavailability is separate from authentication failure and does not clear a valid session. Restored financial identities require a fresh authenticated session; old session cookies remain unusable.
