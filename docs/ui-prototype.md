# Overview prototype

Step 2A provides the local Overview screen and frontend foundation. All financial records, dates, and exchange rates are fictional. Future navigation destinations are visibly marked **Soon** and are not interactive links.

## Behavior

- Responsive sidebar and mobile drawer, Indigo & Apricot light/dark themes, local Inter font, and bundled Lucide icons.
- Tracked assets, invested assets, cash, allocation, six expandable account snapshots, and recent activity.
- INR/USD reporting with original USD amounts labeled in account details.
- 1M/3M/6M value history with pointer exploration, keyboard date slider, and a data table.
- Amount masking covers summary, account details, activity, chart/table data, accessible attributes, and the displayed FX rate. Allocation percentages and account names remain visible.
- Populated, loading, empty, partial/stale, and failed-load demo states. A failed load retains the last usable populated/partial/empty view; retry simulates recovery locally after 650 ms.

The snapshot date is fixed at 20 October 2026. Holdings and price dates are independently displayed in account details. Partial mode leaves one advisor-held mutual fund unpriced, labels known-value coverage, and marks the UBS holdings as stale. History is withheld in partial mode to avoid comparing incomplete current coverage with a complete historical series.

## Theme and chart colors

Light mode pairs pale indigo backgrounds and white panels with warm apricot highlights. Dark mode uses indigo backgrounds and panels with brighter apricot accents. Navigation, summaries, controls, account monograms, history charts, and the favicon follow the palette.

Asset allocation uses separate category colors with matching legend markers:

| Category | Light | Dark |
| --- | --- | --- |
| US equities | `#AD6A3A` | `#F4BC8F` |
| Mutual funds | `#356F9C` | `#7DCDF0` |
| Indian equities | `#8964B5` | `#C4A2F4` |
| Cash | `#8A741D` | `#E8D276` |

Three-pixel separators sit at the exact cumulative allocation boundaries. They remain the same thickness on smaller screens, while the underlying angles and percentages still come from the valued assets. The chart is decorative to assistive technology; the adjacent list supplies class names, amounts, and percentages without relying on color. Theme tokens are in `frontend/src/styles.css`.

## Fixture calculations

`frontend/src/data/portfolio.ts` owns the fictional data and calculation helpers. Amounts start as decimal strings, become `bigint` paise/cents, and retain their original currency. There is no production accounting engine.

The fictional rate is **1 USD = INR 83.50**, dated 20 October 2026. Conversion uses an integer ratio and rounds to the target currency's minor unit, half away from zero. Positions are converted individually to INR before aggregation. Display conversion is applied to those INR values; independently rounded USD rows may differ from a rounded grand total by a cent. Original USD position values remain available in details. Chart coordinates and percentages use floating point only after exact totals are computed.

| Fixture | INR value |
| --- | ---: |
| Invested assets | 47,96,290.00 |
| Bank and broker cash | 2,89,790.00 |
| Tracked assets | 50,86,080.00 |
| Partial-mode valued assets | 46,61,080.00 |
| Partial-mode unpriced holding | Unknown; excluded, not zero |
| Sample spending, excluding transfers/purchases | 2,450.00 |

Account and asset-class totals reconcile to the summary. Bank and broker cash are counted once. The last history point matches the full current snapshot. History describes asset value, not returns; deposits, withdrawals, and currency movements can affect it. The matched bank transfer is not income or spending. These examples do not implement a transfer-matching engine.

## Security boundary

The prototype has no backend, authentication, uploads, provider access, live quotes, analytics, or financial persistence. Only theme, currency, and amount-mask preferences are persisted under `portfolio.display.v1`. Invalid or blocked storage falls back safely. Masking is a display feature; bundled fixture data remains inspectable.

Vite development and preview bind to `127.0.0.1` with fixed ports and host checks. Development file access is restricted to the frontend directory. Both send no-sniff, no-referrer, frame-denial, and camera/microphone/geolocation restrictions. The content policy limits scripts, fonts, images, and connections to the local origin; development adds inline scripts and the local HMR WebSocket for Vite refresh. Dynamic allocation styling requires inline styles. Production preview removes the inline-script exception and sends `frame-ancestors 'none'`; built HTML also contains a fallback content-policy meta tag. Frame restrictions require HTTP headers and cannot be enforced by that meta tag alone.

Future hosting must configure equivalent or stronger headers at its HTTPS entry point. Vite preview is a local inspection server, not a production hosting service. No database, real-data, deployment, or authentication protections are implied by this prototype.

Dependencies are exact-pinned and locked. Installation lifecycle scripts are disabled by `.npmrc`. React/React DOM/Scheduler use MIT, Lucide uses ISC, and Inter uses OFL-1.1; distributed notices are included in `frontend/public/third-party-notices.txt`. Development tooling licenses are recorded in the lockfile. The initial installation audit reported zero known vulnerabilities; advisories can change.

## Verification

Local verification on 21 October 2026:

| Check | Result |
| --- | --- |
| `npm run check` | Passed: 21 tests across three files, TypeScript checks, production build |
| Financial fixtures | Exact totals, allocation/account reconciliation, missing values, negative rounding, currency display, transfer exclusion |
| Component behavior | Currency/range, privacy including hidden DOM text and accessible attributes, state transitions, retry, persisted preferences, blocked/malformed storage |
| Structural accessibility | Axe check passed in jsdom; color contrast checked separately in the browser |
| Responsive browser review | Light/dark screenshots at 1440, 768, and 390 px; no horizontal overflow, including at 320 px with a scrollbar |
| Keyboard | Drawer forward/reverse focus wrap and Escape return; chart slider arrow navigation and data table |
| Text contrast | No failing measured text pairs in either theme, including warning states; gradient-card text also checked, lowest text pair approximately 4.80:1 |
| Allocation contrast | Each segment and matching legend marker contrasts with the panel by at least 4.28:1 in light mode and 6.00:1 in dark mode; three-pixel separators distinguish adjoining segments |
| Production interactions | Currency, privacy, loading, empty reset, partial valuation, error retention, retry; no browser warnings/errors observed |
| Browser policy | Local script/style URLs; production security headers verified, including CSP and frame denial |
| Dependencies | `npm audit --audit-level=low`: zero reported vulnerabilities on 21 October 2026; lockfile licenses reviewed and runtime notices bundled |

Primary header controls are at least 44 px high. Period buttons are 30–37 by 38 px on the reviewed layouts, above the 24 px minimum; at the narrowest breakpoint they are 27 px wide. Reduced-motion CSS disables animation and transitions, but a runtime OS-preference switch was not exercised. Browser automation did not apply 400% zoom, so actual zoom/enlarged-text verification remains pending; the 320 px reflow review is not presented as a substitute for that check. Full screen-reader testing and a complete accessibility audit also remain outstanding.

| View | Light | Dark |
| --- | --- | --- |
| Desktop, 1440 px | [Screenshot](screenshots/overview-1440-light.jpg) | [Screenshot](screenshots/overview-1440-dark.jpg) |
| Tablet, 768 px | [Screenshot](screenshots/overview-768-light.jpg) | [Screenshot](screenshots/overview-768-dark.jpg) |
| Mobile, 390 px | [Screenshot](screenshots/overview-390-light.jpg) | [Screenshot](screenshots/overview-390-dark.jpg) |

[Partial coverage with a simulated load error](screenshots/overview-partial-error-mobile.jpg) demonstrates retained values and coverage messaging. Every screenshot uses fabricated records and the Indigo & Apricot palette. Widths identify the viewport setting; the content area is 15 px narrower where the browser shows a scrollbar. The acceptance targets remain in the [prototype plan](ui-prototype-plan.md).

## Next increment

Investment holdings and detail views are next in the prototype sequence. Banking, budgets, and import/connection walkthroughs follow. Production data and security foundations remain separate work.
