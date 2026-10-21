# Frontend prototype

Step 2A provides the local Overview screen and frontend foundation. Step 2B.1 adds the investment holdings list, and Step 2B.2 adds holding detail pages. All financial records, dates, and exchange rates are fictional. Overview and Investments are available through navigation; other destinations are visibly marked **Soon** and are not interactive links.

## Behavior

- Responsive sidebar and mobile drawer, Indigo & Apricot light/dark themes, local Inter font, and bundled Lucide icons.
- Tracked assets, invested assets, cash, allocation, six expandable account snapshots, and recent activity.
- INR/USD reporting with original USD amounts labeled in account details.
- 1M/3M/6M value history with pointer exploration, keyboard date slider, and a data table.
- Amount masking covers summary, account details, activity, chart/table data, holding values, quantities, native quotes/NAVs, lot purchases/fees, accessible attributes, and the displayed FX rate. Allocation percentages and account/instrument names remain visible.
- Populated, loading, empty, partial/stale, and failed-load demo states. A failed load retains the last usable populated/partial/empty view; retry simulates recovery locally after 650 ms.

The snapshot date is fixed at 20 October 2026. Holdings and price dates are independently displayed in account details. Partial mode leaves one advisor-held mutual fund unpriced, labels known-value coverage, and marks the UBS holdings as stale. History is withheld in partial mode to avoid comparing incomplete current coverage with a complete historical series.

## Investment holdings

The list contains 14 account-specific holdings: seven stocks, three ETFs, and four funds across INDmoney India, INDmoney US, advisor funds, and UBS. Accenture appears separately in INDmoney US and UBS while sharing instrument identity. Fund records distinguish direct/regular plans, growth/distribution options, and friendly fictional folio labels. The UBS row carries an ESPP label and opens its own lot and activity records.

Search matches names and symbols literally, ignoring case and surrounding whitespace. Instrument type, market, account, native currency, fund plan, and data-status filters combine. Active chips support removal and clear-all. The overall summary stays unchanged by filtering; the matching count and subtotal appear above the results. An entirely unpriced selection shows an unavailable subtotal, while no matches has a separate reset action.

Value, name, portfolio weight, and holdings-date sorting support both directions. Numeric sorts use canonical INR values, with unknown values last and stable holding IDs breaking ties. Weights always use the full known investment total, excluding cash, so filtering to one holding does not turn its weight into 100%. Partial coverage is labeled. Native quotes retain their original currency when reporting values switch between INR and USD. Holdings and quote/NAV dates are separate; date tooltips include year, time, and IST.

Desktop uses a table; narrower layouts use two-column or single-column cards with the same semantic rows and labeled data. The visible Sort selector works on every layout; visually hidden mobile headers have no keyboard stops. Holding-name links have account-specific accessible names and visible focus.

The allowlisted routes are `#/overview`, `#/investments`, and `#/investments/<holding-id>` for known fixture IDs (`h01` through `h14`). An empty route and the earlier `#overview` alias open Overview. Unknown, encoded, or malformed detail paths show an unavailable screen. Search terms, account details, and financial values are not placed in URLs.

Browser Back/Forward restores in-memory screen state and scroll. Detail entry focuses its heading; returning to the list focuses the originating holding link, falling back to the list heading if that row is absent or the detail was opened directly. Search, filters, expanded filter controls, sorting, and scroll survive screen changes but reset on reload. A detail URL still opens that holding after reload; theme, reporting currency, and masking persist.

## Holding details

Each detail page identifies the instrument, account, market, native currency, and applicable fund plan or employee plan. The current position shows reporting value, native value, units, price/NAV, and investment weight from the same fixtures as the list and Overview. Source information separates holdings time, quote time, and the dated fictional FX rate. Desktop places position/source information beside supporting records; narrower layouts stack them.

Fund information retains plan, growth/distribution option, and sample folio identity. Selected purchases, dividends/distributions, and fees belong to the exact holding ID, so the same security at another account does not inherit those records. Some holdings have no supplied activity and say so explicitly. Activity is illustrative, not a complete ledger, and never adds to current valuation. Original-currency purchase and activity amounts do not change when the reporting currency changes.

UBS has three illustrative open ESPP lots with 8, 6.5, and 9.5 remaining units, totaling the holding's 24 shares. Supplied gross purchase amounts are USD 1,964.00, 1,705.60, and 2,629.60. Fees are respectively USD 0.00, unknown, and USD 1.25; the screen distinguishes unknown from zero and keeps fees separate from gross purchases. The sample has no disposals. Purchase amounts are independent source fixtures, checked against the illustrative units and purchase prices, rather than derived from today's quote or current FX. No return or tax-basis calculation is implemented, and cost basis remains unavailable.

Loading and empty details remain navigable. In partial mode, the advisor fund has unknown NAV/value/weight, while its recorded units and selected activity remain available. UBS retains its last known units with a stale label and an independently dated quote. Failed loads retain the last usable state and retry locally. Shared masking covers all monetary values, units, purchase prices, fees, activity values, and FX text. The advisor's holdings timestamp is aligned with its Overview account snapshot at 18 October 2026, 10:00 IST.

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

`frontend/src/data/holdings.ts` owns instrument identities, account/folio snapshots, and dated quotes. Overview derives its investment positions from the same collection in `portfolio.ts`, where cash, history, and summary activity remain. `holdingRecords.ts` holds separate selected activity and employee lots keyed by holding ID. `money.ts` contains exact parsing, rounding, conversion, and formatting helpers. There is no production accounting engine.

Amounts start as decimal strings and become `bigint` paise/cents. Units use eight decimal places and quotes use six, also as scaled integers. Multiplication is exact; native valuation rounds to minor units, half away from zero, before FX conversion. Parsing rejects ambiguous input and excess precision. Floating point is used only for presentation percentages and chart coordinates after exact financial totals are calculated.

The fictional rate is **1 USD = INR 83.50**, dated 20 October 2026. Conversion uses an integer ratio and rounds to the target currency's minor unit, half away from zero. Positions are converted individually to INR before aggregation. Display conversion is applied to those INR values; independently rounded USD rows may differ from a rounded grand total by a cent. Original USD position values remain available in details. Chart coordinates and percentages use floating point only after exact totals are computed.

| Fixture | INR value |
| --- | ---: |
| Invested assets | 47,96,290.00 |
| Bank and broker cash | 2,89,790.00 |
| Tracked assets | 50,86,080.00 |
| Partial-mode known investments | 43,71,290.00 |
| Partial-mode valued assets | 46,61,080.00 |
| Partial-mode unpriced holding | Unknown; excluded, not zero |
| Sample spending, excluding transfers/purchases | 2,450.00 |

Account and asset-class totals reconcile to the summary. Bank and broker cash are counted once. The last history point matches the full current snapshot. History describes asset value, not returns; deposits, withdrawals, and currency movements can affect it. The matched bank transfer is not income or spending. These examples do not implement a transfer-matching engine.

## Security boundary

The prototype has no backend, authentication, uploads, provider access, live quotes, analytics, or financial persistence. Only theme, currency, and amount-mask preferences are persisted under `portfolio.display.v1`. Invalid or blocked storage falls back safely. Holdings controls stay in memory, routes are allowlisted, and searches render as plain text. Hidden values are omitted from rendered DOM and accessible labels. Masking is a display feature; bundled fixture data remains inspectable.

Vite development and preview bind to `127.0.0.1` with fixed ports and host checks. Development file access is restricted to the frontend directory. Both send no-sniff, no-referrer, frame-denial, and camera/microphone/geolocation restrictions. The content policy limits scripts, fonts, images, and connections to the local origin; development adds inline scripts and the local HMR WebSocket for Vite refresh. Dynamic allocation styling requires inline styles. Production preview removes the inline-script exception and sends `frame-ancestors 'none'`; built HTML also contains a fallback content-policy meta tag. Frame restrictions require HTTP headers and cannot be enforced by that meta tag alone.

Future hosting must configure equivalent or stronger headers at its HTTPS entry point. Vite preview is a local inspection server, not a production hosting service. No database, real-data, deployment, or authentication protections are implied by this prototype.

Dependencies are exact-pinned and locked. Installation lifecycle scripts are disabled by `.npmrc`. React/React DOM/Scheduler use MIT, Lucide uses ISC, and Inter uses OFL-1.1; distributed notices are included in `frontend/public/third-party-notices.txt`. Development tooling licenses are recorded in the lockfile. The initial installation audit reported zero known vulnerabilities; advisories can change.

## Verification

Local verification on 21 October 2026:

| Check | Result |
| --- | --- |
| `npm run check` | Passed: 56 tests across seven files, TypeScript checks, production build |
| Financial fixtures | Exact totals, allocation/account reconciliation, fractional valuation and rounding, missing values, duplicate-security identity, currency display, transfer exclusion, fixed weight denominator, lot-unit reconciliation, supplied purchase amounts and distinct unknown/zero fees |
| Component behavior | Combined holdings filters, literal search, numeric/stable sorting, missing values last, all 14 direct detail links, native acquisition amounts, currency/range, privacy including hidden DOM text and accessible attributes, originating-row focus, state transitions, retry, persisted preferences, blocked/malformed storage |
| Structural accessibility | Axe check passed in jsdom; color contrast checked separately in the browser |
| Responsive browser review | Light/dark screenshots at 1440, 768, and 390 px; no horizontal overflow, including at 320 px with a scrollbar |
| Keyboard | Drawer forward/reverse focus wrap and Escape return; destination heading focus, visible mobile sorting without hidden tab stops; chart slider arrow navigation and data table |
| Text contrast | No failing measured text pairs in either theme, including warning states; gradient-card text also checked, lowest text pair approximately 4.80:1 |
| Allocation contrast | Each segment and matching legend marker contrasts with the panel by at least 4.28:1 in light mode and 6.00:1 in dark mode; three-pixel separators distinguish adjoining segments |
| Production interactions | Holdings search/filters, currency/privacy across routes, loading, empty reset, partial valuation, error retention/retry, Back/Forward and reload; no browser warnings/errors observed |
| Browser policy | Local script/style URLs; production security headers verified, including CSP and frame denial |
| Dependencies | `npm audit --audit-level=low`: zero reported vulnerabilities on 21 October 2026; lockfile licenses reviewed and runtime notices bundled |

Primary header controls are at least 44 px high. Period buttons are 30–37 by 38 px on the reviewed layouts, above the 24 px minimum; at the narrowest breakpoint they are 27 px wide. Reduced-motion CSS disables animation and transitions, but a runtime OS-preference switch was not exercised. Browser automation did not apply 400% zoom, so actual zoom/enlarged-text verification remains pending; the 320 px reflow review is not presented as a substitute for that check. Full screen-reader testing and a complete accessibility audit also remain outstanding.

Holdings search, selects, and primary filter controls are at least 44 px high; removable filter chips are at least 32 px high. Holding-name and Back to holdings links are at least 44 px high. Text-pair measurements found no failures in either holdings theme (lowest measured pair approximately 4.81:1 light and 5.93:1 dark). Detail measurements were approximately 4.81:1 light and 6.91:1 dark for the normal view; gradient endpoints were checked separately. Structural tests run without the jsdom color-contrast rule; axe emits a canvas-support warning, so browser measurements supply contrast evidence. No dependencies changed in Step 2B.

### Overview screenshots (Step 2A)

| View | Light | Dark |
| --- | --- | --- |
| Desktop, 1440 px | [Screenshot](screenshots/overview-1440-light.jpg) | [Screenshot](screenshots/overview-1440-dark.jpg) |
| Tablet, 768 px | [Screenshot](screenshots/overview-768-light.jpg) | [Screenshot](screenshots/overview-768-dark.jpg) |
| Mobile, 390 px | [Screenshot](screenshots/overview-390-light.jpg) | [Screenshot](screenshots/overview-390-dark.jpg) |

[Partial coverage with a simulated load error](screenshots/overview-partial-error-mobile.jpg) demonstrates retained values and coverage messaging. Every screenshot uses fabricated records and the Indigo & Apricot palette. Widths identify the viewport setting; the content area is 15 px narrower where the browser shows a scrollbar. The acceptance targets remain in the [prototype plan](ui-prototype-plan.md).

### Holdings screenshots (Step 2B.1)

| View | Light | Dark |
| --- | --- | --- |
| Desktop, 1440 px | [Screenshot](screenshots/holdings-1440-light.jpg) | [Screenshot](screenshots/holdings-1440-dark.jpg) |
| Tablet, 768 px | [Screenshot](screenshots/holdings-768-light.jpg) | [Screenshot](screenshots/holdings-768-dark.jpg) |
| Mobile, 390 px | [Screenshot](screenshots/holdings-390-light.jpg) | [Screenshot](screenshots/holdings-390-dark.jpg) |

[Unpriced advisor holding with a simulated load error](screenshots/holdings-partial-error-mobile.jpg) shows the known total and unavailable filtered subtotal. Source dates and all other figures are fictional.

### Holding detail screenshots (Step 2B.2)

| UBS ESPP view | Light | Dark |
| --- | --- | --- |
| Desktop, 1440 px | [Screenshot](screenshots/holding-detail-1440-light.jpg) | [Screenshot](screenshots/holding-detail-1440-dark.jpg) |
| Tablet, 768 px | [Screenshot](screenshots/holding-detail-768-light.jpg) | [Screenshot](screenshots/holding-detail-768-dark.jpg) |
| Mobile, 390 px | [Screenshot](screenshots/holding-detail-390-light.jpg) | [Screenshot](screenshots/holding-detail-390-dark.jpg) |

[Unpriced regular fund with a simulated load error](screenshots/holding-detail-fund-partial-dark.jpg) shows unknown valuation alongside recorded units, fund identity, and selected activity.

## Next increment

[Step 2C](banking-prototype-plan.md) is planned in three increments: HDFC/SBI activity and transaction inspection (2C.1), transfer matching review (2C.2), and category corrections (2C.3). Banking is not yet implemented. Budgets and import/connection walkthroughs follow. Production data and security foundations remain separate work.
