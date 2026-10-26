# Protected bank activity: Step 8A.1

The protected Banking entry reads saved HDFC and SBI bank accounts directly, without an investment position. It uses only the existing account directory, event query and event-history routes. It adds no provider connection, parser, financial mutation or balance calculation.

## Scope and navigation

Opening Banking loads one page of saved accounts. The directory response includes every account type; only eligible HDFC/SBI bank accounts on that page are offered, including archived accounts. Next/previous controls retain the original directory cursor even if a page has no matching banks. An empty visible page does not establish that no bank accounts exist. Account selection and activity inspection remain explicit.

Saved activity is ordered by opaque event identity, not date. Each event appears at its latest retained revision, including pending and cancelled evidence. Revision history is newest first and may contain a newer revision than the one opened. Source, coverage, dates and exact values can change between revisions. Returning from history refetches account activity; choosing another account refetches the directory and discards the previous financial context.

Cash movements, fees and withholding retain their native signs and precision. No income, spending category, merchant, transfer pairing or running balance is inferred. Booking, value, trade and settlement dates remain separate, alongside the explicit cash date basis. Compact cards keep amounts, booking/value dates, cash date basis and record states visible. Ordering and revision explanations, opaque identities and source metadata sit in keyboard-accessible expandable details. Cancelled evidence has no components and creates no synthetic reversal or zero movement.

## Validation and privacy

[Bank projections](../frontend/workspace/src/banking-evidence.ts) reuse strict account and event validation. An impossible bank institution/market combination fails closed. Every event and historical revision binds to the selected account, has no position/instrument association, and uses only that selected account's validated native currencies. HDFC/SBI identity does not imply INR-only. A changed currency set requires a fresh directory read; rows are never silently dropped or the set automatically widened.

The shared account-bound event page keeps exact fields, native values, role/sign/date rules, latest-revision flags, canonical identities and 25-row cursor checks. The investment wrapper continues to enforce the originating position/instrument binding. History retains event identity, descending safe revisions, current flags and the clicked revision lower bound; a known event cannot return an empty first history page as valid evidence. Other-account data, position-linked bank evidence and regressed/malformed responses block the workspace.

Only the current page and bounded cursor metadata are retained. Loads and failures remove earlier values. Navigation, session replacement, lock and sign-out discard the selected context, while generation/unmount guards ignore late responses. Initial directory loading is deferred while the authentication controller is busy and protected against duplicate effect setup; unavailable reads require explicit retry.

Existing MFA, same-origin POST/CSRF, owner isolation, no-store and response-size controls apply. Financial values, including zero and missing-value placeholders, are masked in text, accessible content and attributes. Display preferences never convert native evidence. No browser storage, private bank reference, sample fallback, automatic retry, backend route, schema or dependency is added.

## Verification

The 70 focused Banking tests pass. They cover mixed directory pagination, impossible bank combinations, bank-native currency and position restrictions, shared investment binding, event/history paging, changed historical sources, empty/regressed history, exact values, masking, loading/error clearing, initial StrictMode/busy-session behavior, keyboard entry and late-response disposal. All 288 affected account, activity, investment, workspace, frozen-input and receipt cases passed in the combined run. TypeScript and both production builds pass.

Synthetic Chromium checks at 1440px and 390px cover light/dark account lists, activity and revision history, explicit account choice, automatic first directory loading, keyboard/focus and expandable explanations/source details, archived-account switching and exact native values under display-currency changes. Zero and missing-value placeholders and historical values remain masked; browser storage stays empty. Boundary probes preserve mixed directory cursors, activity/history pagination and refresh, then verify complete clearing for impossible bank positions and undeclared native currency. Browser accessibility checks report zero WCAG A/AA violations including contrast; the revision button's accessible name includes its visible label. The mobile navigation fits four tabs at 390px and retains a wrapping fallback. No horizontal overflow or browser page error was observed, and the preview process and port were closed after checks.

The captures use synthetic account labels and financial evidence only. No private statement, live bank or provider compatibility is exercised. Local focused checks do not replace the full integrated verification gate.

| View | Desktop light / dark | Mobile light / dark |
| --- | --- | --- |
| Saved bank accounts | [Light](images/protected-bank-activity/accounts-1440-light.png) / [Dark](images/protected-bank-activity/accounts-1440-dark.png) | [Light](images/protected-bank-activity/accounts-390-light.png) / [Dark](images/protected-bank-activity/accounts-390-dark.png) |
| Saved activity | [Light](images/protected-bank-activity/activity-1440-light.png) / [Dark](images/protected-bank-activity/activity-1440-dark.png) | [Light](images/protected-bank-activity/activity-390-light.png) / [Dark](images/protected-bank-activity/activity-390-dark.png) |
| Revision history | [Light](images/protected-bank-activity/history-1440-light.png) / [Dark](images/protected-bank-activity/history-1440-dark.png) | [Light](images/protected-bank-activity/history-390-light.png) / [Dark](images/protected-bank-activity/history-390-dark.png) |
