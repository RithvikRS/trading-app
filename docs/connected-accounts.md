# Connected account directory

Step 5E.1 connects the protected workspace's **Accounts** page to saved account identities through the [owned financial read API](financial-reads.md). It is the first connected financial screen. Provider connections, account creation, imports, balances and investment values remain separate work. An installation with no saved accounts shows an explicit empty state.

## What the page means

Each row shows the saved label, institution, account kind, market, native currencies and active/archived state. An active account is an active workspace record; it does not establish a live provider connection, current balance or complete import history. Archived records remain visible for inspection. No source account number, protected provider reference, owner identifier or internal revision is rendered.

INR/USD display preferences do not convert account identity. Native currencies remain labeled and unchanged, including when amount masking is off. This directory contains no financial amounts or invented zero balances. Imported labels render as plain text.

The Overview page remains an empty financial overview and provides navigation to Accounts. Desktop navigation and compact mobile navigation expose the same pages. Entering a page moves keyboard focus to its main heading. Loading, empty and unavailable states have distinct messages; temporary failures never become an empty directory.

## Access and transient data

The directory opens only after the server session and preferences have been checked. Its `POST /api/v1/finance/accounts/query` request uses the existing same-origin cookie, signed CSRF and [sign-in context](workspace-context.md) controls. It accepts no owner selector. The server independently enforces MFA, expiry, revocation, ownership and forced database isolation.

Responses must have the existing no-store JSON headers and a validated exact shape, bounded fields and a maximum of 256 KiB. This endpoint's response allowance does not widen the smaller authentication/preference response limit or its 4 KiB JSON request limit. Redirects and cross-origin requests remain disallowed. No provider key or direct database access enters the browser. Separate [snapshot review](reviewed-snapshots.md) preview/completion requests have their own exact-path body limits.

Only the current page and a bounded cursor history remain in memory. Starting a refresh or page change removes the prior page. Lock, sign-out, page hiding, offline state, local expiry, invalid responses, access denial and a changed sign-in discard the private workspace. Generation checks ignore late results from an earlier session. A normal session renewal preserves the current page; a replacement sign-in cannot inherit it. An unavailable or rate-limited account read hides that page and allows an explicit retry while the session remains valid. No automatic retry keeps a session active.

Account records and cursors are not written to URLs, browser storage, telemetry or a service worker. These controls do not promise physical erasure of browser memory or instantaneous revocation in a suspended tab; the existing server and [page lifecycle limitations](protected-workspace.md) still apply.

## Pagination and freshness

The API returns up to 25 records in ascending UUID order. The client rejects duplicates, reversed/before-cursor records, oversized pages and inconsistent continuation values. Next and Previous re-read their cursor boundaries; previous page contents are not cached. The view keeps at most 100 page cursors and explicitly reports if additional records lie beyond that limit. Back to first page restarts traversal.

Pagination is a series of owned reads rather than a frozen directory snapshot. Concurrent edits may change labels or page contents; a newly inserted lower UUID can appear only after returning to the first page. Refresh re-reads the current page. The page does not claim automatic provider synchronization or an exhaustive total from one page.

## Verification and visual evidence

Synthetic component/client cases cover request binding, strict account contracts, pagination, current-page retention, timeout/expiry, replacement sessions, late responses, access denial, unavailable retry, text-only labels, focus and accessibility semantics. Existing PostgreSQL tests cover the endpoint's owner isolation and browser controls; the UI does not introduce a new backend query.

The following captures use an isolated development harness with fabricated responses. The harness, test identities and response overrides are excluded from application sources and both production builds. They do not establish hosted Supabase authentication or provider connectivity.

| State | Light | Dark |
| --- | --- | --- |
| Desktop, 1440px | [Accounts](images/connected-accounts/accounts-light-desktop.png) | [Accounts](images/connected-accounts/accounts-dark-desktop.png) |
| Mobile, 390px | [Accounts](images/connected-accounts/accounts-light-mobile.png) | [Accounts](images/connected-accounts/accounts-dark-mobile.png) |

[Empty directory](images/connected-accounts/accounts-empty.png) and [unavailable directory](images/connected-accounts/accounts-unavailable.png) have separate recovery guidance. Browser review checked both themes, loaded local Inter fonts, keyboard entry, saved display choices and no horizontal overflow at 1440, 390 and 320 pixels. Four browser accessibility audits, including contrast, reported no violations: desktop light/dark, 320px light and 390px dark. Actual device and assistive-technology acceptance remains separate.

## Migration and recovery

No schema, database privilege, dependency, source adapter or recovery-format change is introduced. The page uses the existing current-schema account endpoint and the coordinated frontend/API sign-in-context contract. Deploy only the protected workspace build through the same-origin API; the fictional prototype remains separate. Rebuilding the previous protected frontend can remove this page without changing any account data. Keep the sign-in-context protection and server authorization controls active.
