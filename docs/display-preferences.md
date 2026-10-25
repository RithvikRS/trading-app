# Step 3F.2: Authenticated display preferences

The protected workspace saves appearance, display currency, and amount privacy to the signed-in owner's PostgreSQL record. Settings load only after a verified session and a successful authenticated preference read. The existing fictional prototype remains separate; its browser preferences are never read or copied into the account.

## Display behavior

| Situation | Behavior |
| --- | --- |
| Signed out or locked | System light/dark appearance; no account settings or financial content remain in memory |
| First sign-in, no saved row | System appearance, INR, and amounts hidden; clearly labeled as unsaved defaults |
| Saved account settings | Saved light/dark, INR/USD, and masking choices take precedence over system and pre-sign-in appearance |
| Editing | Changes remain a draft. Save applies them only after server acknowledgement; Discard restores the loaded settings |
| Changed in another tab/device | Save returns a conflict. Keep the draft visible, disable another save, and offer **Reload saved settings**, which explicitly discards the draft |
| Failed or uncertain save | Lock the workspace and explain that the save was not confirmed. Recheck the session and reload saved settings before another attempt |
| Session expiry, sign-out, offline, hidden tab, or page departure | Clear loaded settings and drafts; ignore late responses. Returning requires session and preference checks |

Settings do not poll across devices. They reload when the workspace reopens or after an explicit conflict reload. Routine session checks preserve the current draft and do not extend idle time. Preference reads and saves also leave the idle and absolute deadlines unchanged; **Keep session active** remains the only explicit idle-extension action.

The protected workspace still has no financial records. Currency and masking are saved choices for future reporting, with the current choice shown in the empty workspace. They do not convert source records or authorize access. An unmasked account choice is applied only after successful authentication and loading. No preference, revision, identity, draft, provider token, or financial record goes into local/session storage, IndexedDB, a URL, or a service worker.

## API contract

Both routes require an active, fully verified MFA session, bound CSRF header, and the existing same-origin browser boundary. Pending login and restricted recovery sessions cannot read or write preferences. Ownership comes exclusively from the validated server session and exact issuer/subject mapping.

| Route | Contract |
| --- | --- |
| `GET /api/v1/preferences` | Return exactly `theme`, `display_currency`, `amount_masked`, and `revision`; never create a row on read |
| `PUT /api/v1/preferences` | Require all four fields. `theme` is `light` or `dark`, currency is `INR` or `USD`, masking is a JSON boolean, and revision is an integer from 0 through 9007199254740991 |

Revision 0 means no persisted row. Its canonical API values are light/INR/masked; the browser resolves system appearance for this unsaved state only. A first save inserts revision 1 only if a row is still absent. Subsequent updates require the exact loaded revision and increment it in the database. Missing/extra fields, ownership/timestamp fields, string booleans/numbers, and out-of-range values are rejected without echoing the payload. Query parameters and bearer authorization are rejected. Responses use `Cache-Control: no-store`.

A stale insert/update returns HTTP 409 with the existing fixed error envelope, without returning another version's fields or invalidating a valid session. The client never overwrites automatically. A successful response must match the submitted values and next revision before it can change the display. All mutation attempts are single-shot. A lost response can leave a committed save whose result the browser does not know; reloading determines the stored state. See [HTTP conflict semantics](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Status/409).

## Ownership, transactions, and revocation

The API refreshes and verifies the provider session through the existing authentication service, then stores the rotated encrypted provider state. Provider network work finishes before workspace SQL begins. A short authentication transaction acquires the same advisory lock used by session renewal/revocation, validates the active session, and holds that lock across the separate runtime preference transaction and its commit. The API rechecks session expiry and the active owner/mapping immediately before the runtime commit.

This orders application revocation against saves: revocation completed first denies the save; a save holding the guard commits before waiting revocation completes. Expected revision conflicts leave authentication intact. Failure inside the runtime transaction rolls back its write and clears pooled owner context. The runtime role still cannot access session/identity tables, assign ownership, write revisions/timestamps, or change policies. The authentication role still cannot read or write preferences. Forced RLS remains active for every owner-scoped runtime query.

The two roles use separate bounded connections, not a distributed transaction. If connection/response delivery fails after commit, the result is uncertain and must be read again. Expiry checks cannot undo a transaction already committed. Out-of-band privileged SQL does not participate in the application's advisory-lock protocol: committed owner/mapping changes are checked again before commit, but an arbitrary administrative mutation is not globally atomic with in-flight work. Use the documented session/owner revocation path for account access changes. The global guard suits the current personal application; resource/concurrency measurement belongs to Step 3G. [PostgreSQL transaction and advisory locking](https://www.postgresql.org/docs/17/explicit-locking.html).

## Migration and recovery

Migration `0005_preference_revisions` adds a bounded, non-null bigint revision with initial value 1 and extends the existing update trigger to advance it. Existing theme, currency, masking, and timestamps are preserved on upgrade. No table, ownership policy, or role grant is added. Run from `backend/` after the [local database setup](database-foundation.md):

```powershell
& .venv/Scripts/python.exe -m trading_db migrate
& .venv/Scripts/python.exe -m trading_db status
```

Apply the migration before enabling the updated authenticated API, rebuild both frontend outputs, and restart the API as described in the [protected workspace runbook](protected-workspace.md). Startup does not migrate automatically. A missing revision column causes preference access to fail closed. Authentication-disabled installations remain locked and create no owner or preference row.

The migration is additive and the previous application can coexist with the new column; old internal writes also advance the trigger. Production/development recovery uses a forward fix or the previous application while retaining the additive schema. Downgrade/re-upgrade is exercised only in disposable tests: values survive, but revision history is reset. Do not downgrade a database serving active clients. If disabling the frontend, revoke sessions separately when required; switching off static delivery is not revocation.

## Verification and review

Local PostgreSQL tests exercise defaults without insertion, restart persistence, two-owner isolation, strict payloads, browser boundary checks, pending/recovery/expired/disabled/removed/remapped identity denial, provider failure, stale and simultaneous writes, revocation ordering, rollback after SQL, pool cleanup, revision privileges/bounds, and upgrade/downgrade/failure atomicity. Synthetic provider responses pass through the real HTTP adapter; no hosted credentials are used.

Frontend tests cover delayed loads, account precedence, draft/discard/save, explicit conflict reload and focus, response validation, unavailable reads, uncertain saves, timeout, expiry, and stale responses after locking. Existing authentication, prototype, and build-isolation checks remain active. Run all five local [shared check groups](verification.md); record their actual results separately from any optional manual CI run.

Browser captures use synthetic responses in an isolated Chromium context with the actual production assets and CSP. They are UI evidence, not proof of hosted Supabase behavior.

| View | Light | Dark |
| --- | --- | --- |
| Desktop, 1440px | [Light](images/display-preferences/workspace-1440-light.png) | [Dark](images/display-preferences/workspace-1440-dark.png) |
| Mobile, 390px | [Light](images/display-preferences/workspace-390-light.png) | [Dark](images/display-preferences/workspace-390-dark.png) |

Local Windows verification on 24 October 2026 passed all four shared check groups: 15 verification-helper tests, 243 backend tests, 185 PostgreSQL tests, and 556 frontend tests. Ruff, mypy, TypeScript, both builds, workflow policy/actionlint, 367 local documentation links, and source/history secret scans passed. Python/npm audits reported no known vulnerabilities. Browser review passed six axe audits including contrast, keyboard selection, desktop/mobile reflow, save/conflict/reload, restoration of saved settings after page reload, and sign-out reset, with no browser storage or page errors. The unmocked authentication-disabled build stayed locked. All four captures were visually reviewed. Existing prototype canvas-test and bundle-size warnings remain. Actual GitHub CI results are recorded in the PR.

The local development database was upgraded to `0005_preference_revisions`; all seven application tables retained their existing empty row counts. No test identity or preference row was seeded into development.

Hosted Supabase authentication/database TLS and pooling, cross-device delivery against a live provider, assistive-technology review on physical devices, and deployment remain unverified. No real identity or financial data is introduced. The subsequent [Step 3G](local-packaging.md) adds local packaging and recovery evidence; hosted checks remain outstanding.

[Step 5E.0](workspace-context.md) requires `X-Workspace-Context` from the checked session on reads and saves. HTTP 412 indicates a replaced sign-in and clears the workspace; HTTP 409 remains a preference revision conflict. Initial loading cannot combine one session response with another sign-in's preferences.
