# Protected account-activity inspection: Step 7B.2

Investment details now open saved account activity, event revisions and source-coverage records through the existing [event history reads](event-lot-reads.md). The account-wide scope is explicit: opening from one holding does not filter out other positions or account-level cash. No provider access, financial write, parser, migration or new API is introduced.

## Scope and navigation

Select a saved holding and choose **Inspect account activity**. The screen identifies the account and originating holding. Each page contains up to 25 latest event revisions, including pending and cancelled evidence, in ascending opaque identity order. This is not chronological ordering. An event that references the originating holding must retain that holding's known instrument identity on every page and refresh. Other positions and account-level cash are labeled separately and remain on the page; no hidden client filter makes an incomplete page look complete.

**Inspect revisions** opens the selected event's retained history in descending revision order. Identity, account, position, instrument and event kind remain bound to that event. Source, coverage, reported period, dates, posting state and components belong to each revision and can differ. A live history read may include a newer revision than the list entry that opened it. Its first returned revision cannot be older than that opened revision; later pages can contain older revisions. Latest/earlier navigation replaces the previous page. An empty page never establishes zero activity or full history.

Each event revision can open its source-coverage records. These are the selected source's reports and replacement links, potentially covering other events or positions. Current/superseded evidence and snapshot, partial, unknown or source-claimed complete coverage remain distinct. Reported periods are never joined, and source claims do not establish reviewed or reconciled completion. Return to current activity reloads the account's first page.

## Financial meaning

Posted versus pending, active versus cancelled, and latest versus historical are independent states. A cancelled current revision has no components; prior values remain visible only in history. Cancellation creates no inferred reversing transaction or zero movement. A pending event never contributes to a displayed posted balance.

Trade, settlement, booking and value dates are displayed independently, alongside the supplied cash date basis. Missing dates remain unavailable. Date ordering, settlement completion and a default date basis are not inferred.

Quantities and cash retain exact signed decimal strings, trailing zeros and native INR/USD currencies. Changing the display preference does not convert source evidence. Required movements, optional gross cash, unit price, fees and withholding retain their source roles; missing details differ from supplied zero. Components, events and pages are not summed. The view calculates no account balance, spending, cash-flow total, gain, tax result, return or completeness claim.

## Privacy and read boundaries

Only fixed authenticated POST routes are used: account-bound `/events/query`, event-bound `/events/history`, and source-bound `/imports/observations/query`. The existing MFA session, exact-origin/CSRF, workspace context, no-store, ownership and bounded-response protections apply. Requests contain opaque identities and cursors without private provider references or financial values.

[Activity projections](../frontend/workspace/src/activity-evidence.ts) reject unknown fields, foreign scope, inconsistent identities, malformed dates/revisions/cursors, duplicate or unsupported components, numeric money, unsupported currencies and incompatible movement signs. History binds immutable identity while permitting revised source evidence. Malformed responses enter the existing blocked protocol screen; an unavailable read uses a generic error and clears preceding values.

[ActivityInspection](../frontend/workspace/src/ActivityInspection.tsx) keeps one bounded view in memory. Loading, failure, navigation, sign-out and workspace replacement discard earlier views; late responses cannot reopen an unmounted view. Masking removes all financial amounts and quantities, including historical, zero and missing-value details, from visible and accessible content. No amount is encoded in URLs, titles, ARIA values, charts or geometry. No browser storage, automatic retry or fabricated fallback is introduced.

## Verification

[Synthetic tests](../frontend/src/test/workspace-activity.test.tsx) cover exact/native values, account-wide pages, independent states/dates, changed history sources and periods, all three pagination paths, malformed and foreign responses, masking, absent/archived evidence, unavailable reads, keyboard focus and late responses after navigation, lock and sign-out. The integrated revision receives the [standard verification groups](verification.md).

This feature inspects already saved evidence. [UBS source feasibility](ubs-integration-plan.md), actual acquisition formats, complete historical coverage and hosted/provider compatibility remain separate work.

### Local validation evidence

The focused activity, lot and investment tests pass together: **140 tests**. TypeScript and both production builds also pass. The demo build retains its existing bundle-size warning. Synthetic Chromium checks passed at 1440 px and 390 px in both themes, including keyboard entry and focus, unchanged native values after currency-preference changes, current/history masking, zero and missing evidence, WCAG A/AA accessibility and contrast, horizontal reflow, empty browser storage, and sign-out clearing. Separate browser probes also confirm that an originating-instrument mismatch and a regressed first history page enter the blocked protocol screen and remove prior financial values. No real provider session or financial record was used.

| View | Desktop light | Desktop dark | Mobile light | Mobile dark |
| --- | --- | --- | --- | --- |
| Account activity | [Light](images/account-activity-inspection/activity-1440-light.png) | [Dark](images/account-activity-inspection/activity-1440-dark.png) | [Light](images/account-activity-inspection/activity-390-light.png) | [Dark](images/account-activity-inspection/activity-390-dark.png) |
| Event revisions | [Light](images/account-activity-inspection/history-1440-light.png) | [Dark](images/account-activity-inspection/history-1440-dark.png) | [Light](images/account-activity-inspection/history-390-light.png) | [Dark](images/account-activity-inspection/history-390-dark.png) |
| Source coverage | [Light](images/account-activity-inspection/coverage-1440-light.png) | [Dark](images/account-activity-inspection/coverage-1440-dark.png) | [Light](images/account-activity-inspection/coverage-390-light.png) | [Dark](images/account-activity-inspection/coverage-390-dark.png) |