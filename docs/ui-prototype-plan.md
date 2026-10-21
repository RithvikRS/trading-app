# UI prototype plan

The prototype establishes visual design and everyday interactions before connecting financial accounts. Step 2A implements the Overview and minimum frontend foundation; [implementation notes](ui-prototype.md) describe its behavior and verification. Later screens remain planned.

## Scope and visual direction

The Overview answers three questions: what assets are tracked, where they are held, and which data needs attention. React, TypeScript, and Vite provide a reusable frontend foundation with a small, pinned dependency set.

Use the Indigo & Apricot palette: pale indigo backgrounds and warm apricot highlights in light mode, deeper indigo surfaces and bright apricot accents in dark mode. Keep readable type, tabular numbers, thin separators, and limited elevation. Allocation charts use four distinct hues, contrasting separators, and matching labeled legends. Follow the system theme initially and offer an explicit control. Bundle fonts and icons locally. Accompany meaningful color with text or icons.

Desktop uses a narrow sidebar; mobile uses a compact header and navigation drawer. Keep a neutral working title. Favor useful charts and compact account rows, respect reduced motion, and preserve keyboard access.

The prototype runs on loopback with fabricated fixtures. Backend services, databases, authentication, real statements, provider connections, live quotes, trading, and deployment are outside its scope. Keep a visible sample-data label on every screen size.

## Increments

| Increment | Deliverable | Status |
| --- | --- | --- |
| 2A | Frontend foundation, responsive shell, Overview | Implemented locally |
| 2B | Searchable/filterable/sortable holdings and holding details | Planned |
| 2C | Banking activity, sample transfer matching, category review | Planned |
| 2D | Budgets, cash flow, monthly categories, recurring items | Planned |
| 2E | Import-review walkthrough and connection status with bundled samples | Planned |

Refine each increment after reviewing the preceding screen. Future destinations may appear with planned status, but must not resemble working links. Import walkthroughs use fixtures without file inputs or provider sign-in.

## Overview requirements

| Area | Behavior |
| --- | --- |
| Header | Demo label, INR/USD, hide/show amounts, theme |
| Summary | Assets, investments, cash, clear currency and snapshot date |
| History | 1M/3M/6M ranges, dated values, keyboard exploration, table |
| Allocation | Labeled classes, amounts, percentages, accessible list |
| Accounts | INDmoney, advisor funds, UBS, HDFC, SBI; distinct holdings/balance and price dates |
| Attention | Stale/incomplete data, affected accounts, explained coverage |
| Activity | Purchases, dividends, transfers, spending; full history follows later |

Use **Tracked assets**, since liabilities and complete coverage are not established. Count bank and broker cash once. Account totals, allocation, and summary must reconcile. History describes value changes including cash flows and FX, not investment return. Return, tax, and trading calculations are outside this increment.

Currency conversion uses a labeled, dated fictional rate. Preserve original-currency values and document minor-unit arithmetic and rounding. Changing a chart range does not alter the current summary.

## Interactions and states

- Theme, currency, privacy, chart range, drawer, and disclosures support keyboard and pointer input.
- Privacy hides absolute amounts in text, labels, tables, and accessible attributes. It is visual privacy, not encryption or authentication.
- Demo controls select populated, loading, empty, partial/stale, and failed-load states without contacting providers.
- Loading uses skeletons instead of false zeros. Empty explains missing sample accounts and offers a reset.
- Missing prices remain unknown and are excluded from labeled known-value totals. Stale holdings retain their dates.
- Failed loads retain the last usable view with a simulated local retry.
- The drawer contains focus and returns it to its trigger on dismissal. Chart details are available without hover.

Persist only display preferences. Financial fixtures remain bundled/in memory. Exclude uploads, credentials, account-connect actions, analytics, remote fonts, and external runtime requests.

## Acceptance evidence

| Area | Target |
| --- | --- |
| Visual quality | 1440 px desktop, 768 px tablet, 390 px mobile in both themes |
| Reflow | No page-wide horizontal scroll at 320 px; enlarged text and 400% zoom |
| Accessibility | Landmarks, named controls, visible focus, keyboard flows, chart alternatives, reduced motion |
| Contrast/targets | 4.5:1 normal text, 3:1 large text; 44 px primary touch targets where practical |
| Financial integrity | Reconciliation, consistent currency, transfers excluded from spending, accurate coverage/freshness |
| Privacy | No hidden-amount leaks; synthetic records and local runtime assets |
| Behavior | Five states, theme/currency/privacy/range controls, retry, drawer focus |
| Engineering | Types, production build, meaningful tests, dependency/license review |

See W3C guidance for [contrast](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html), [target size](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html), and [reflow](https://www.w3.org/WAI/WCAG22/Understanding/reflow.html). These targets are not a claim of full accessibility conformance. Record actual evidence and limits in the implementation notes.
