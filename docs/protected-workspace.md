# Step 3F.1: Protected frontend shell

The protected application now has its own entry point, sign-in and authenticator screens, restricted password recovery, session controls, and an empty workspace. It uses the existing Indigo & Apricot light/dark design. Financial records, account connections, imports, and saved preferences are not available in this build. Step 3F.2 introduces the first authenticated preference API.

## Separate builds and local entry

| Build | Source | Output | Local entry |
| --- | --- | --- | --- |
| Fictional prototype | `frontend/src/main.tsx` | `frontend/dist/` | Existing Vite development/preview commands on 5173/4173 |
| Protected workspace | `frontend/workspace/src/main.tsx` | `frontend/workspace/dist/` | FastAPI on `http://127.0.0.1:8000/` when enabled |

`npm run build` type-checks both applications and builds each independently. `npm run build:workspace` rebuilds only the protected assets. A module-graph guard fails the protected build if it imports any prototype source except the shared design stylesheet. The build has no public-directory copy, source maps, environment-variable injection, service worker, Supabase SDK, or provider key. A failed API request never loads the prototype or sample balances.

After the [Python setup](development.md#local-python-api), run from the repository root:

```powershell
Set-Location frontend
npm run build
Set-Location ../backend
$env:TRADING_API_FRONTEND_ENABLED = 'true'
& .venv/Scripts/python.exe -m trading_api
```

Without authentication configuration the shell displays a connection-unavailable state. This is expected: there is no development login, fabricated identity, or successful authentication fallback. No Supabase project has been configured. Local component/browser checks supply synthetic responses exclusively inside the test harness.

For a future dedicated test project, first follow the [provider](authentication-foundation.md) and [session](browser-sessions.md#local-setup-and-verification) runbooks, including restricted enrollment, owner mapping, local PostgreSQL migrations and session key custody. Enable `TRADING_API_AUTH_ENABLED=true` only with that configuration. Use the exact `127.0.0.1` address and configured API port; the prototype's Vite origin cannot authenticate to the API. No CORS or Origin relaxation is introduced.

Static delivery is deliberately small: only `/` and the build's JS/CSS/font assets are served. The fixed build directory is read once at startup, with allowed file types, per-file and total size limits, no symbolic links, and no request-to-filesystem resolution. Missing/incomplete builds fail startup. Unknown paths, query strings, source files, source maps, and API paths never fall back to HTML. Rebuild and restart the API to load changed assets. All delivered assets use no-store, no-referrer, nosniff, frame denial, restricted permissions, and a same-origin CSP without inline scripts/styles. API responses keep their stricter existing CSP. Hosted TLS/proxy/container delivery remains Step 3G work.

## Browser behavior

| State | Behavior |
| --- | --- |
| Initial check | Render only the gate; bootstrap CSRF, then verify the server session before opening the workspace |
| Sign-in | Email/password with password-manager autocomplete and paste; no public registration; form fields cleared on submission |
| First MFA enrollment | Display the setup key in memory for manual time-based authenticator entry; verify a six-digit code; clear setup material when the flow ends |
| Existing MFA | Select an existing authenticator when two are available; submit a six-digit code; an unsuccessful attempt requires a new sign-in |
| Recovery | Show email recovery only when bootstrap reports it enabled; generic email response, email code, existing authenticator, then new password; a fresh sign-in is required afterward |
| Active workspace | Explicit empty content; no financial totals, persisted preferences, or sample records; theme follows the system initially and can change in memory |
| Expired or revoked | Hide the workspace, discard earlier requests and clear transient state; local expiry also attempts server sign-out, with uncertain revocation shown separately |
| Forbidden, offline, unavailable, invalid response, or limited | Hide protected content; fixed explanation and deliberate retry; never render provider error bodies |
| Sign-out | Immediately hide content; revoke locally through the API; distinguish confirmed sign-out, unavailable provider cleanup, and unconfirmed server revocation |

The browser accepts only bounded, validated API response shapes. Fetch is same-origin, cookie-based, no-store, no-referrer, redirect-denying, and time-limited. Requests use signed CSRF, including the session GET. The bootstrap response now includes the non-sensitive boolean `recovery_email_enabled`; it reveals no identity or credentials. HTTP Date anchors conservative session countdowns independently of browser wall-clock skew.

Requests within a tab are serialized. A generation guard and abort signal discard results from an earlier session after locking, sign-out, or component cleanup. Mutations are never automatically retried. Rate limiting exposes a short retry delay. A visible workspace checks revocation about once a minute without extending idle expiry; server-side validation remains authoritative. Only the explicit **Keep session active** action extends idle time. There is no automatic heartbeat that keeps an unattended session alive.

Hiding an active workspace clears it from the rendered page. Returning to that tab or restoring a history entry requires a new session check. Page navigation also clears incomplete authentication material. A `BroadcastChannel` sends only a constant lock signal to other tabs after sign-out/recovery; it carries no identity, secrets, or financial data. Browsers can suspend or terminate pages without delivering lifecycle events, so these UI measures supplement server expiry/revocation rather than replacing them. See [page lifecycle limitations](https://developer.mozilla.org/en-US/docs/Web/API/Window/pagehide_event).

No password, MFA setup key, code, session metadata, provider token, or financial record is written to local/session storage, IndexedDB, URLs, telemetry, or a service worker. Only the server's opaque HttpOnly session cookie and readable signed CSRF cookie are used. This increment stores no theme preference; it does not read the prototype's display preferences. Amount masking has no disclosure control yet because the workspace contains no amounts.

Backup-factor enrollment/removal remains available through the existing backend contract and operator runbook; this shell implements initial enrollment, selecting existing factors, and restricted password recovery. It provides no bypass for loss of every authenticator. The UI is not an authorization boundary: future workspace endpoints must independently verify identity and enforce database ownership.

## Accessibility and review evidence

Authentication screens use explicit labels, standard autocomplete, paste-friendly fields, native validation, focus movement to new headings, error/status announcements, and 44px or larger interactive targets. Reduced motion disables the loading animation. The layout adapts to narrow screens without horizontal scrolling. All-session sign-out has an inline confirmation; there is no keyboard-trapping modal.

The following captures use synthetic responses in an isolated headless Chromium test context. They contain no real identity, financial records, or enrolled MFA secret. They demonstrate UI behavior, not a hosted Supabase authentication result.

| Screen | Light | Dark |
| --- | --- | --- |
| Desktop sign-in, 1440px | [Light](images/protected-workspace/signin-1440-light.png) | [Dark](images/protected-workspace/signin-1440-dark.png) |
| Mobile sign-in, 390px | [Light](images/protected-workspace/signin-390-light.png) | [Dark](images/protected-workspace/signin-390-dark.png) |
| Desktop empty workspace, 1440px | [Light](images/protected-workspace/workspace-1440-light.png) | [Dark](images/protected-workspace/workspace-1440-dark.png) |
| Mobile empty workspace, 390px | [Light](images/protected-workspace/workspace-390-light.png) | [Dark](images/protected-workspace/workspace-390-dark.png) |

Automated component tests cover sign-in/MFA/recovery, password-manager/paste behavior, focus, themes, offline/visibility/history transitions, and accessibility semantics. Client tests cover strict response parsing, CSRF omission, bounded payloads, secret clearing, time limits, serialization, stale responses, uncertain sign-out, and recovery restrictions. Build-guard tests reject prototype imports. Backend tests cover opt-in delivery, headers, file/size boundaries, missing routes, traversal, and absence of an authentication bypass. The existing PostgreSQL suite still exercises real session/identity isolation with synthetic provider responses.

Use the [shared verification commands](verification.md) for repository, backend, database and frontend checks. Browser review additionally checks the built application at both sizes and themes, runs axe including contrast, checks overflow/storage, and walks sign-in, MFA and all-session sign-out. Hosted provider behavior, email delivery, actual devices/password managers/screen readers, TLS cookies, and deployment configuration remain unverified.

Local Windows evidence on 24 October 2026: repository checks passed with 15 helper tests, workflow validation, 342 local links and secret scans; 243 backend and 138 PostgreSQL tests passed. The full frontend run passed 521 tests, types, both builds and its dependency audit. After the timeout correction, all 45 protected-client/component/build tests passed, including two new timeout cases (523 frontend tests now defined). The final build passed eight browser axe audits including contrast, desktop/mobile overflow checks, keyboard entry, sign-in/MFA/sign-out, and storage checks. A separate unmocked browser check confirmed that disabled authentication cannot open the workspace. Python/npm audits reported no known vulnerabilities. Existing prototype canvas-test and bundle-size warnings remain. Actual CI results for the final revision are recorded in the PR.

## Migration and recovery

No database migration or credential change is introduced. Existing installations keep the liveness-only default unless authentication/frontend options are explicitly enabled. To disable static delivery, unset `TRADING_API_FRONTEND_ENABLED` or set it to `false` and restart. This does not revoke existing sessions; use the [session revocation procedure](browser-sessions.md) when revocation is needed. Never deploy the prototype output as the protected build. Retain the backend session API and use forward fixes if an active installation needs recovery.
