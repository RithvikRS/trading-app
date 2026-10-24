# Workspace requests bound to a sign-in

Step 5E.0 binds preference reads/writes and financial reads to the exact browser sign-in that opened the workspace. It precedes connected financial screens and can progress independently of statement-format support.

## Shared-cookie problem

Browser tabs share the session cookie. A tab can retain old display choices or account data after another tab replaces that cookie with a new sign-in. Cookie authentication alone would authorize the new session while the older screen still describes the previous one. A client-provided owner ID cannot solve this safely.

The checked session response now includes `workspace_context`, a 64-character lowercase hexadecimal view marker. The server derives it from the session cookie verifier using a separately derived HMAC-SHA256 key in the existing session vault. It exposes neither the cookie, its verifier, provider tokens nor an owner identifier. It is stable across renewal and application restart with the same vault key, and changes when the sign-in cookie changes. The marker is not an authentication credential and cannot authorize a request by itself.

## Request and failure contract

Every `/api/v1/preferences` read/write and `/api/v1/finance/*` read requires `X-Workspace-Context` containing the marker from the checked session. The server verifies the cookie, bound CSRF, active MFA and owner mapping, then compares this marker before entering any financial database transaction. Duplicate context headers are rejected at the browser boundary.

A missing, malformed or mismatched marker returns HTTP 412 with a fixed `workspace_context_changed` error. This expected stale-view failure occurs outside the authentication lease's revocation path: it neither clears the browser cookie nor revokes a valid replacement session. It creates no preference or financial record. A correct subsequent request can continue. Missing/invalid authentication still fails under the existing authentication rules; a marker never bypasses those checks.

The frontend binds its initial preference read to the session response it just checked, and binds subsequent preference reloads/saves to the same marker. A periodic session check with a different marker clears the workspace. HTTP 412 also clears private state and displays a session-recheck action, distinct from a preference revision conflict. Rechecking performs a new session-and-preferences sequence; the browser cannot carry old choices into the replacement context automatically.

Beginning sign-in or recovery verification broadcasts the existing constant lock signal to other tabs. The message contains no marker, account identity or credential. This improves prompt clearing when broadcast delivery is available; server context enforcement and periodic checks remain necessary when it is not. An in-flight response cannot establish that another tab has not changed cookies since that request began, so no instantaneous cross-tab invalidation guarantee is claimed.

Context markers and private responses stay in memory, out of URLs, browser storage and broadcast messages. Do not add request-header logging. Existing exact-origin, MFA, CSRF, expiry, revocation, no-store, owner/RLS and transaction guards remain required. All future connected financial calls must send the marker from their currently checked session and discard stale asynchronous responses.

## Compatibility and verification

This is a coordinated private API/frontend contract change. Deploy matching bundles: older clients lack the required marker and fail closed, and must reload. There is no schema, grant, dependency or recovery-format change. Restored financial data still requires a fresh sign-in; session state remains excluded from recovery.

Fabricated tests cover stable versus replaced markers, domain separation, invalid inputs, duplicate headers, rejection before financial SQL, unchanged valid sessions after rejection, two-owner replacement, initial-load races, stale saves, periodic rechecks and healthy recovery. The marker is also rejected as a session cookie. These checks do not establish hosted Supabase configuration or production deployment readiness.

See [browser sessions](browser-sessions.md), [display preferences](display-preferences.md), [financial reads](financial-reads.md) and the [investment flow](investment-flow-plan.md).
