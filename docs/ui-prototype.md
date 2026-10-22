# Frontend prototype

Step 2A provides the local Overview screen and frontend foundation. Steps 2B.1 and 2B.2 add investment holdings and details; Steps 2C.1–2C.3 add banking activity, inspection, transfer matching, and category corrections. Step 2D.1 adds monthly category budgets; Step 2D.2 adds historical cash-flow trends; Step 2D.3 adds recurring-expense review; Step 2E.1 adds connection-status and source-coverage walkthroughs; Steps 2E.2–2E.3 add bank sample inspection and reversible import reviews; Step 2E.4 adds investment statement walkthroughs. All financial records, dates, and exchange rates are fictional. Overview, Investments, Banking, Budgets, and Connections are available through navigation; other destinations are visibly marked **Soon** and are not interactive links.

## Behavior

- Responsive sidebar and mobile drawer, Indigo & Apricot light/dark themes, local Inter font, and bundled Lucide icons.
- Tracked assets, invested assets, cash, allocation, six expandable account snapshots, and recent activity.
- INR/USD reporting across every primary monetary display, including expanded account rows, prices/NAVs, selected activity, ESPP lots, bank rows, reconciliation, and inspection. Differing original amounts are labeled separately.
- 1M/3M/6M value history with pointer exploration, keyboard date slider, and a data table.
- Amount masking covers summary, account details, activity, chart/table data, holding values, quantities, native quotes/NAVs, lot purchases/fees, accessible attributes, and the displayed FX rate. Allocation percentages and account/instrument names remain visible.
- Populated, loading, empty, partial/stale, and failed-load demo states. A failed load retains the last usable populated/partial/empty view; retry simulates recovery locally after 650 ms.

The snapshot date is fixed at 20 October 2026. Holdings and price dates are independently displayed in account details. Partial mode leaves one advisor-held mutual fund unpriced, labels known-value coverage, marks the UBS holdings as stale, and removes one SBI activity row while retaining its independently supplied balance. History is withheld in partial mode to avoid comparing incomplete current coverage with a complete historical series.

## Investment holdings

The list contains 14 account-specific holdings: seven stocks, three ETFs, and four funds across INDmoney India, INDmoney US, advisor funds, and UBS. Accenture appears separately in INDmoney US and UBS while sharing instrument identity. Fund records distinguish direct/regular plans, growth/distribution options, and friendly fictional folio labels. The UBS row carries an ESPP label and opens its own lot and activity records.

Search matches names and symbols literally, ignoring case and surrounding whitespace. Instrument type, market, account, native currency, fund plan, and data-status filters combine. Active chips support removal and clear-all. The overall summary stays unchanged by filtering; the matching count and subtotal appear above the results. An entirely unpriced selection shows an unavailable subtotal, while no matches has a separate reset action.

Value, name, portfolio weight, and holdings-date sorting support both directions. Numeric sorts use canonical INR values, with unknown values last and stable holding IDs breaking ties. Weights always use the full known investment total, excluding cash, so filtering to one holding does not turn its weight into 100%. Partial coverage is labeled. Prices/NAVs and values follow the reporting currency; differing original quotes remain labeled beneath their display equivalents. The native-currency filter still selects instrument source currency. Holdings and quote/NAV dates are separate; date tooltips include year, time, and IST.

Desktop uses a table; narrower layouts use two-column or single-column cards with the same semantic rows and labeled data. The visible Sort selector works on every layout; visually hidden mobile headers have no keyboard stops. Holding-name links have account-specific accessible names and visible focus.

The allowlisted routes are `#/overview`, `#/investments`, and `#/investments/<holding-id>` for known fixture IDs (`h01` through `h14`). An empty route and the earlier `#overview` alias open Overview. Unknown, encoded, or malformed detail paths show an unavailable screen. Search terms, account details, and financial values are not placed in URLs.

Browser Back/Forward restores in-memory screen state and scroll. Detail entry focuses its heading; returning to the list focuses the originating holding link, falling back to the list heading if that row is absent or the detail was opened directly. Search, filters, expanded filter controls, sorting, and scroll survive screen changes but reset on reload. A detail URL still opens that holding after reload; theme, reporting currency, and masking persist.

## Holding details

Each detail page identifies the instrument, account, market, native currency, and applicable fund plan or employee plan. The current position shows reporting value, native value, units, price/NAV, and investment weight from the same fixtures as the list and Overview. Source information separates holdings time, quote time, and the dated fictional FX rate. Desktop places position/source information beside supporting records; narrower layouts stack them.

Fund information retains plan, growth/distribution option, and sample folio identity. Selected purchases, dividends/distributions, and fees belong to the exact holding ID, so the same security at another account does not inherit those records. Some holdings have no supplied activity and say so explicitly. Activity is illustrative, not a complete ledger, and never adds to current valuation. Primary purchase and activity amounts follow the reporting currency, with differing originals shown beneath them. Dated demo FX produces display equivalents only, not purchase-date FX, returns, or tax basis. Source records do not change.

UBS has three illustrative open ESPP lots with 8, 6.5, and 9.5 remaining units, totaling the holding's 24 shares. Supplied gross purchase amounts are USD 1,964.00, 1,705.60, and 2,629.60. Fees are respectively USD 0.00, unknown, and USD 1.25; the screen distinguishes unknown from zero and keeps fees separate from gross purchases. The sample has no disposals. Purchase amounts are independent source fixtures, checked against the illustrative units and purchase prices, rather than derived from today's quote or current FX. No return or tax-basis calculation is implemented, and cost basis remains unavailable.

Loading and empty details remain navigable. In partial mode, the advisor fund has unknown NAV/value/weight, while its recorded units and selected activity remain available. UBS retains its last known units with a stale label and an independently dated quote. Failed loads retain the last usable state and retry locally. Shared masking covers all monetary values, units, purchase prices, fees, activity values, and FX text. The advisor's holdings timestamp is aligned with its Overview account snapshot at 18 October 2026, 10:00 IST.

## Banking activity and inspection

Banking contains 28 original-INR records across HDFC and SBI: 26 posted and two pending. Search matches description, counterparty, and friendly sample reference literally. Account, inclusive booking-date range, direction, posting status, effective category, and review-status filters combine. Effective transfer classifications are separate from read-only source categories. Date/amount/description sorting supports both directions with stable identity ties. Legitimate repeated payments remain separate. Invalid date ranges withhold movement totals; ranges beyond supplied coverage explain the limitation.

Bank cards show independent booked-balance snapshots. Expand Source details to see opening balance, calculated closing balance, statement-minus-calculated difference, activity date, and period coverage. Monetary fields follow the selected reporting currency with labeled original INR amounts; reconciliation arithmetic remains in native minor units. The account/date-range movement summary includes transfers and is labeled money in/out, not income/spending. Search and other classification filters only affect the matching-result subtotals. Pending entries are counted separately and excluded from posted movements and reconciliation. There is no synthetic running balance.

| Complete statement fixture | HDFC INR | SBI INR |
| --- | ---: | ---: |
| Opening balance | 1,77,285.90 | 38,199.00 |
| Posted credits | 95,800.00 | 43,250.00 |
| Posted debits | 86,665.90 | 6,599.00 |
| Closing balance | 1,86,420.00 | 74,850.00 |

The period is 1–20 October 2026, through the balance cutoff at 10:00 IST. Both accounts reconcile in the complete fixture. Partial mode removes SBI's INR 2,200 bill, labels activity stale/incomplete, and shows a difference of INR -2,200 without changing the supplied closing balance. HDFC/SBI snapshots feed Overview directly; broker cash remains outside Banking. Overview's selected bank activity uses these same source records and current review decisions. Unlinking the initial pair changes the Overview excerpt to an unreviewed movement. Its initial INR 2,450 spending example is an excerpt, not a full-period spending calculation; its category follows corrections and clearing it makes the excerpt unresolved.

`#/banking` and known `#/banking/t01`–`#/banking/t28` routes are allowlisted. The inspector is a native modal panel on the right on desktop and full width on mobile; the background is inert until closed. It displays original narration/reference, booking/value dates, amount/direction, source period, separate balance/activity dates, and original category alongside effective classification and current pair evidence. Absent value dates stay unsupplied. A known record missing from partial/empty data gets an unavailable inspector; unknown identifiers get the shared unavailable route. No raw URL content is echoed.

Search, filters, expanded controls, sort, and list scroll survive navigation. Inspection focuses its heading, contains keyboard focus, supports Escape, and returns focus to the originating row or the list heading. Direct reload opens the inspector with default list controls. An inspector privacy control changes the same global masking preference; raw narration/reference are removed while hidden. All displayed amounts, including closed source disclosures and background content, follow shared masking. Only display preferences persist.

Bank cards, scope summaries, matching-result subtotals, transaction rows, reconciliation fields, and the inspector’s primary amount all follow the global reporting currency. Differing original INR amounts are labeled separately, and source narration remains verbatim. This uses the dated demo FX rate for display, never historical FX or a change to source amounts. Recorded categories stay read-only. Transfer review (Step 2C.2) and category corrections (Step 2C.3) update effective classifications separately from source fields.

## Transfer matching review

Banking has Activity and Transfers views. Review uses all loaded source records regardless of activity filters; each leg outside those filters is labeled and remains inspectable. The originating review link, selected status, activity filters, and scroll survive inspection and navigation. No extra financial data or decisions enter URLs or browser storage.

The initial review queue contains one suggested pair (HDFC debit/SBI credit of INR 8,000), two ambiguous pairs (one INR 5,000 debit with two competing credits), one unmatched INR 3,500 debit, one seeded confirmed INR 25,000 pair, and no dismissed candidates. Suggested/ambiguous/dismissed counts refer to pairs; unmatched counts refer to records. Pending records and known non-transfer activity are outside candidate generation.

Candidates require distinct posted entries in different known accounts with the same fictional owner, opposite directions, exactly equal positive native amounts and currency, and booking dates within three calendar days. Dates are validated and compared in UTC as calendar dates. Only unresolved/source-transfer roles qualify. Equal amounts/dates suggest a pair but do not prove a transfer. Matching structured sample references are supporting evidence; narration similarity is not a matching rule. Fees, purchases, refunds, salary, investment funding, and other known non-transfer records remain separate.

| Action | Behavior |
| --- | --- |
| Review pair / Confirm this pair | Preview the exact two records, then explicitly confirm. All eligibility and exclusive-membership checks run again before both legs receive one transfer classification. A stale/conflicting action fails without a partial update. Repeated confirmation is idempotent. |
| Dismiss / Restore | Change only the selected candidate pair. Competing alternatives remain available; restored candidates cannot reuse a record already confirmed elsewhere. |
| Unlink | Remove the pair overlay from both records and expose their previous classifications together. Original amounts/narration are never overwritten. The model preserves an underlying manual classification from category review. |
| Undo last change | Reverse the latest applicable confirm, dismiss, restore, or unlink action atomically. An inverse that would recreate an incomplete/conflicting pair is skipped; if none can apply, show an explanation. This is local demo history, not a durable audit log. |
| Reset sample decisions | Clear decisions and history and restore only the initial pair whose source legs are available. Display preferences and original records remain unchanged. |

Confirmed transfers appear once in review totals and are excluded from income/spending classification even when the activity filters show only one leg. Gross account/date money-in/out still includes each posted ledger entry. Unresolved posted outgoing and incoming amounts are displayed separately as coverage, not spending/income. Initially these are INR 16,500 outgoing and INR 18,000 incoming; confirming the unique pair reduces them to INR 8,500 and INR 10,000. The separate INR 5.90 fee remains an expense record. The category workflow below supplies a separate scoped classified-spending preview.

Populated/partial/loading/error modes preserve compatible decisions. Missing or ineligible source legs make the whole retained pair unresolved and exclude it from confirmed totals; the remaining leg is reserved until unlink, preventing reuse. Restored source coverage can make the retained pair valid again. Partial mode warns that only available activity is considered. Empty mode clears decisions/history/selection; loading the populated sample reinstates initial evidence. Reload resets all review decisions. The inspector and Overview read the same effective classification as Banking.

Every reporting amount uses the shared INR/USD preference, including pair previews and coverage. Masking removes displayed original/converted amounts and raw/structured references; action messages and counts contain no amounts. Unknown, zero, pending, and incomplete states stay distinct. Source accounting, dated balance snapshots, and the Overview baseline remain unchanged.

## Category review and corrections

Banking's Categories view has Needs review, Suggestions, Reviewed, and All records queues, with independent account, booking-date, direction, and literal text filters. The initial Needs review queue contains nine records: six unresolved posted movements, one unresolved pending credit, and two already source-categorized café purchases with suggestions to review. Three supplied receipt suggestions cover the two distinct café records and the unresolved household-supplies payment. These are bundled fictional evidence, not merchant enrichment or inferred ownership. Suggestions never change effective categories until accepted and do not overwrite manual or cleared decisions.

Open a record to inspect the original source category alongside its effective category, provenance, and review status. The category editor accepts a suggestion, sets a direction-compatible category, or clears the effective category to unresolved. Every edit has a preview before application. Expense choices include groceries, dining, shopping, utilities, housing, transport, health, subscriptions, fees, and other expense; income choices include salary, interest, and other income. A clear decision remains unresolved even if the original source category was supplied; Undo restores the previous classification and provenance.

Bulk selection is explicit and applies only to visible eligible records. Changing filters, status, or Banking view clears selection and its preview. Preview shows the selected count, each current-to-new classification, linked-refund effects, and exclusions with reasons. Applying revalidates the source identity, amount/currency, posting state, ownership, direction/role, current classification, and pair membership against the preview. Any stale preview fails without applying a subset. Eligible changes form one shared history entry; Undo reverses the batch together or skips it when it cannot be restored safely. Repeating an applied decision cannot add a duplicate correction. Transfer and category actions share the same local history and Reset sample decisions action.

Pending records cannot be corrected before posting. Retained transfer pairs must be unlinked before category edits; transfer overlays preserve underlying manual categories. Investment funding keeps its separate role. Refunds cannot be changed directly to income or expense: the verified sample credit follows the linked Home essentials purchase category, including after correction, clearing, and Undo. Missing purchase evidence, mismatched ownership/currency, an excessive credit, or an uncategorized purchase makes the refund unresolved. This is validation of one supplied link, not a general refund-matching workflow.

The classified-spending preview uses the selected account/date scope, independently of search, direction, and queue status. Full loaded records supply refund evidence even when the purchase is outside the date filter. Posted gross expenses, verified refunds, and net classified spending are distinct from unresolved outgoing/incoming coverage. Refunds count once in their own booking period and offset the purchase category; a refund-only period can have negative net spending. Pending entries, investment funding, and confirmed transfers do not enter classified spending. Source ledger totals and dated balance snapshots remain unchanged.

| Initial complete fixture | INR |
| --- | ---: |
| Gross classified expenses | 36,764.90 |
| Verified refund | 800.00 |
| Net classified spending | 35,964.90 |
| Unresolved posted outgoing | 16,500.00 |
| Unresolved posted incoming | 18,000.00 |

Accepting the household-supplies suggestion adds INR 3,500 to classified expenses and removes it from unresolved outgoing coverage. Clearing the INR 3,200 purchase also makes its INR 800 refund unresolved: gross/net classified spending becomes INR 33,564.90, with unresolved outgoing/incoming of INR 19,700/18,800. The credit and debit remain original source records. Partial mode excludes the missing SBI bill without changing its independent bank balance.

Decisions survive app navigation and compatible partial/loading/error states. Loading or changing source coverage clears pending selections/previews; empty mode clears decisions and history. Reload clears every review decision. Inspector editing retains keyboard containment, Escape, and return to the originating link; if the reviewed row leaves its queue, focus returns to the category heading. The Overview activity excerpt reads the same effective classification. All preview, refund, and coverage amounts follow INR/USD and shared masking, while announcements contain counts and categories without monetary values. No new financial storage, export, credential, backend, network, or payment capability is introduced.

## Monthly category budgets

`#/budgets` provides an October 2026 plan across both HDFC and SBI, with eight supplied INR limits and all ten expense categories. Full-month limits are compared with available posted activity through 20 October, 10:00 IST, without proration. Utilities and Health initially exceed their limits, Housing and Subscriptions exactly match, Health has an explicit zero target, and Bank fees/Other expense have no limit. Over-limit categories appear first, with stable taxonomy order otherwise. Cash flow provides August/September/October history in its own view; the monthly budget plan remains October across both banks. Recurring is labeled Planned.

| Initial plan | INR |
| --- | ---: |
| Planned category limits | 38,199.00 |
| Spending in budgeted categories | 35,959.00 |
| Provisional remaining | 2,240.00 |
| Spending without a category limit | 5.90 |
| All net classified spending | 35,964.90 |

Budgeted plus unbudgeted actuals reconcile to Banking's classified-spending preview. Expense debits and verified refunds use the existing effective classifications and full loaded refund evidence. A refund is attributed to its purchase category in the refund's booking period, even when that purchase falls outside the period. Pending records, investments, confirmed transfers, and unresolved entries remain outside classified spending. A negative category actual stays a net refund; remaining can exceed the original limit. Original transactions, dated bank balances, and the Overview asset baseline are unchanged.

Source coverage and classification coverage are separate: the complete fixture covers both statements through the cutoff but still contains six unresolved posted movements. The coverage disclosure shows INR 16,500 outgoing, INR 18,000 incoming, and two pending entries. Missing source records or unresolved posted activity make remaining amounts and category statuses provisional. An observed zero does not establish zero spending. The partial fixture excludes the missing SBI bill, reduces budgeted actuals to INR 33,759, and preserves independent balance snapshots. Remaining is a difference against category limits, never available cash or a forecast.

Expand a category to see gross expenses, verified refunds, net spending, and contributing source records. Inspection uses the existing Banking dialog with category corrections. The session-only origin restores Budgets, its expanded category, scroll, and exact record link on return; a record that moves to another category falls back to the category heading. Direct transaction reload still opens ordinary Banking inspection. Back/Forward, mobile navigation, and category corrections share the same model and display preferences.

The limit editor accepts exact decimal INR strings from zero through 999999999.99, at most two decimal places, with a 32-character input bound. It rejects empty, negative, comma-separated, exponent, non-finite, oversized, and excess-precision input without rounding or losing the draft. USD reporting shows a labeled equivalent while the editor remains explicitly INR. Add/Edit, Cancel, Remove category limit, Undo budget change, and Reset sample budgets operate only on local planning data. Zero and Not set are distinct; removing every limit shows No budgets set, while actual spending remains visible. Unchanged saves do not create history.

Budget history is separate from Banking review history. Neither domain's reset rewrites the other. Compatible partial/loading/error/retry and navigation preserve decisions; loading hides values and closes the editor. Empty clears planning/review state, and restoring populated or partial samples reinstates the supplied defaults. Reload clears all planning/review edits, retaining only existing display preferences. Budget ownership and month are fixed to the known sample scope; invalid scopes cannot accept edits.

INR/USD applies to limits, actuals, remaining/over-limit values, summaries, coverage, detail breakdowns, and original/converted source records. Masking removes these values and the progress geometry from the DOM. An open editor replaces the monetary input with a neutral placeholder, keeps its draft only in memory, and disables Save/Remove until amounts are shown; a dialog privacy control makes this reversible. Dialogs contain keyboard focus, support Escape/Cancel, and restore their trigger. Status announcements contain no amounts. No financial data, planning state, or history is written to browser storage, URLs, logs, or external services.

Budget state, bounded parsing, monthly actuals, and summaries live in `frontend/src/data/budgets.ts`. The workspace and editor are `Budgets.tsx` and `BudgetEditor.tsx`, with shared display/money helpers and `budgets.css`. There are no new dependencies or backend capabilities.

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

`frontend/src/data/holdings.ts` owns instrument identities, account/folio snapshots, and dated quotes. Overview derives its investment positions from the same collection in `portfolio.ts`, where broker cash, history, and selected investment activity remain. Bank snapshots, source transactions, selectors, and reconciliation live in `banking.ts`; Overview consumes its balances and selected activity. `holdingRecords.ts` holds separate selected investment activity and employee lots keyed by holding ID. `money.ts` contains exact parsing, rounding, conversion, and formatting helpers. The review model in `transfers.ts` owns transfer eligibility, effective classification, shared in-memory decisions/history, and transfer coverage. `categories.ts` owns category constraints, supplied suggestions, change previews, verified refund attribution, and classified-spending calculations. There is no production accounting engine.

Amounts start as decimal strings and become `bigint` paise/cents. Units use eight decimal places and quotes use six, also as scaled integers. Multiplication is exact; native valuation rounds to minor units, half away from zero, before FX conversion. Parsing rejects ambiguous input and excess precision. Floating point is used only for presentation percentages and chart coordinates after exact financial totals are calculated.

The fictional rate is **1 USD = INR 83.50**, dated 20 October 2026. Conversion uses an integer ratio and rounds to the target currency's minor unit, half away from zero. Quote display conversion preserves the six-decimal quote scale rather than first rounding quotes to cents; original quote precision is retained. Display conversions always start from source records, preventing cumulative drift when toggling repeatedly. Positions are converted individually to INR before aggregation. Display conversion is applied to those INR values; independently rounded USD rows may differ from a rounded grand total by a cent. Original USD position values remain available in details. Chart coordinates and percentages use floating point only after exact totals are computed.

| Fixture | INR value |
| --- | ---: |
| Invested assets | 47,96,290.00 |
| Bank and broker cash | 2,89,790.00 |
| Tracked assets | 50,86,080.00 |
| Partial-mode known investments | 43,71,290.00 |
| Partial-mode valued assets | 46,61,080.00 |
| Partial-mode unpriced holding | Unknown; excluded, not zero |
| Sample spending, excluding transfers/purchases | 2,450.00 |

Account and asset-class totals reconcile to the summary. Bank and broker cash are counted once. The last history point matches the full current snapshot. History describes asset value, not returns; deposits, withdrawals, and currency movements can affect it. The matched bank transfer is not income or spending. Transfer matching is a local fixture review model; it does not import data or execute bank transfers.

## Security boundary

The prototype has no backend, authentication, uploads, provider access, live quotes, analytics, or financial persistence. Transfer/category decisions, selections, correction previews, and shared undo history remain in memory. Only theme, currency, and amount-mask preferences are persisted under `portfolio.display.v1`. Invalid or blocked storage falls back safely. Holdings controls stay in memory, routes are allowlisted, and searches render as plain text. Hidden values are omitted from rendered DOM and accessible labels. Masking is a display feature; bundled fixture data remains inspectable.

Vite development and preview bind to `127.0.0.1` with fixed ports and host checks. Development file access is restricted to the frontend directory. Both send no-sniff, no-referrer, frame-denial, and camera/microphone/geolocation restrictions. The content policy limits scripts, fonts, images, and connections to the local origin; development adds inline scripts and the local HMR WebSocket for Vite refresh. Dynamic allocation styling requires inline styles. Production preview removes the inline-script exception and sends `frame-ancestors 'none'`; built HTML also contains a fallback content-policy meta tag. Frame restrictions require HTTP headers and cannot be enforced by that meta tag alone.

Future hosting must configure equivalent or stronger headers at its HTTPS entry point. Vite preview is a local inspection server, not a production hosting service. No database, real-data, deployment, or authentication protections are implied by this prototype.

Dependencies are exact-pinned and locked. Installation lifecycle scripts are disabled by `.npmrc`. React/React DOM/Scheduler use MIT, Lucide uses ISC, and Inter uses OFL-1.1; distributed notices are included in `frontend/public/third-party-notices.txt`. Development tooling licenses are recorded in the lockfile. The initial installation audit reported zero known vulnerabilities; advisories can change.

## Verification

Local verification on 21 October 2026:

| Check | Result |
| --- | --- |
| `npm run check` | Passed: 299 tests across twenty files, TypeScript checks, production build; subsequent affected checks are recorded under Step 2D.3 below |
| Financial fixtures | Exact totals, allocation/account reconciliation, fractional valuation and rounding, missing values, duplicate-security identity, currency display, transfer exclusion, fixed weight denominator, lot-unit reconciliation, supplied purchase amounts and distinct unknown/zero fees |
| Component behavior | Combined holdings filters, literal search, numeric/stable sorting, missing values last, all 14 direct detail links, converted acquisition displays and unchanged source records, currency/range, privacy including hidden DOM text and accessible attributes, originating-row focus, state transitions, retry, persisted preferences, blocked/malformed storage |
| Banking accounting | HDFC/SBI opening/posted movement/closing reconciliation; unchanged Overview totals; pending exclusion; partial discrepancy without balance adjustment; repeated payments preserved; immutable source accessors |
| Banking behavior | Combined filters and inclusive booking dates, invalid ranges, scope versus matching totals, stable sorting, all 28 direct inspectors, consistent reporting USD with labeled original INR, current pair evidence, absent records, browser history, retained controls/scroll, focus containment/return, and narration/amount masking |
| Transfer integrity | Unique/competing/unmatched candidates, native currency/amount/owner/date constraints, atomic confirmation, exclusive membership, repeated actions, pair-specific dismissal/restore, unlink/undo, incomplete source coverage, prior classification restoration, and unchanged ledger/balance totals |
| Transfer interactions | Two-stage confirmation, source inspection outside activity filters with exact link focus return, shared Overview classification, preserved decisions across navigation/partial/error/retry, empty/reset/reload behavior, INR/USD and masking across coverage, pairs, source inspection, and status announcements |
| Category integrity | Direction/role restrictions, unapplied suggestions, preserved manual provenance, exact bulk previews/exclusions, stale-preview rejection, atomic shared undo, refund attribution across date filters, incomplete/excessive refund exclusion, and unchanged ledger/balance/assets |
| Category interactions | Individual and bulk review, visible-only selection, selection clearing on filters/status, source/effective inspection, shared Overview updates, currency/privacy, preserved decisions and reset/reload behavior, keyboard focus and structural axe checks |
| Budget integrity and interactions | Exact bounded inputs, zero/unset limits, edit/remove/cancel/undo/reset, source-linked refunds and classifications, partial coverage, currency/privacy including open drafts and progress geometry, navigation/focus, and separate review histories |
| Structural accessibility | Axe check passed in jsdom; color contrast checked separately in the browser |
| Responsive browser review | Light/dark screenshots at 1440, 768, and 390 px; no horizontal overflow, including at 320 px with a scrollbar |
| Keyboard | Drawer forward/reverse focus wrap and Escape return; destination heading focus, visible mobile sorting without hidden tab stops; chart slider arrow navigation and data table |
| Text contrast | No failing measured text pairs in either theme, including warning states; gradient-card text also checked, lowest measured pair approximately 4.73:1 |
| Allocation contrast | Each segment and matching legend marker contrasts with the panel by at least 4.28:1 in light mode and 6.00:1 in dark mode; three-pixel separators distinguish adjoining segments |
| Production interactions | Holdings search/filters, currency/privacy across routes, loading, empty reset, partial valuation, error retention/retry, Back/Forward and reload; no browser warnings/errors observed |
| Browser policy | Local script/style URLs; production security headers verified, including CSP and frame denial |
| Dependencies | `npm audit --audit-level=low`: zero reported vulnerabilities on 21 October 2026; lockfile licenses reviewed and runtime notices bundled |

Primary header controls are at least 44 px high. Period buttons are 30–37 by 38 px on the reviewed layouts, above the 24 px minimum; at the narrowest breakpoint they are 27 px wide. Reduced-motion CSS disables animation and transitions, but a runtime OS-preference switch was not exercised. Browser automation did not apply 400% zoom, so actual zoom/enlarged-text verification remains pending; the 320 px reflow review is not presented as a substitute for that check. Full screen-reader testing and a complete accessibility audit also remain outstanding.

Holdings search, selects, and primary filter controls are at least 44 px high; removable filter chips are at least 32 px high. Holding-name and Back to holdings links are at least 44 px high. Text-pair measurements found no failures in either holdings theme (lowest measured pair approximately 4.81:1 light and 5.93:1 dark). Detail measurements were approximately 4.81:1 light and 6.91:1 dark for the normal view; gradient endpoints were checked separately. Structural tests run without the jsdom color-contrast rule; axe emits a canvas-support warning, so browser measurements supply contrast evidence. No dependencies changed in Step 2B.

Banking browser review covered both themes at 1440, 768, and 390 px, with page and inspector reflow at 320 px. Native date-input keyboard changes, literal search, inspector entry/Escape, focus wrap, scroll restoration, direct reload, currency switching, masking, and partial/error recovery were exercised. Normal measured text pairs remained at least approximately 4.81:1 light and 5.93:1 dark; the inspector reuses the verified hero gradient tokens. Production-preview logs showed no warnings/errors. No dependencies changed in Step 2C.1. The outstanding zoom, screen-reader, and runtime reduced-motion checks above still apply.

### Workspace currency verification

The reporting-currency regression suite covers Overview summaries, history, allocation, all expanded accounts, every holding quote/value, all 14 detail pages, all supplied activity/lots, bank balances/reconciliation/subtotals/rows, and all 28 inspectors. It exercises both conversion directions, stable ordering and native-currency filters, immutable source records, negative reconciliation differences, missing values, unknown/zero fees, masking, and saved preferences. Quote rounding is tested independently at six decimal places.

Source-currency identifiers, explicitly labeled native position values, original reference amounts, raw narration, and the FX-rate definition remain in their source currency. Units, dates, classifications, weights, and source filters do not change. Historical display equivalents are not historical FX or tax-basis calculations.

Production-browser checks covered Overview, holdings, UBS details, and Banking in both themes at 1440, 768, 390, and 320 px with no horizontal overflow. USD inspection, masking, direct reload, and Escape were also exercised. Measured non-gradient text pairs remained at least 4.80:1 in light mode and 5.93:1 in dark mode across the four screens; existing gradient tokens are unchanged. No browser warnings/errors were observed. The accessibility limitations recorded above remain outstanding.

New currency evidence complements the earlier milestone screenshots below:

| View | Desktop | Mobile |
| --- | --- | --- |
| Expanded Overview, USD | [Light](screenshots/currency-overview-1440-light.jpg) | [Dark](screenshots/currency-overview-390-dark.jpg) |
| Holdings and NAVs, USD | [Light](screenshots/currency-holdings-1440-light.jpg) | [Dark](screenshots/currency-holdings-390-dark.jpg) |
| UBS lots and activity, INR | [Light](screenshots/currency-detail-1440-light.jpg) | [Dark](screenshots/currency-detail-390-dark.jpg) |
| Bank activity, USD | [Dark](screenshots/currency-banking-1440-dark.jpg) | [Light](screenshots/currency-banking-390-light.jpg) |

[USD transaction inspection](screenshots/currency-inspector-390-light.jpg) shows the selected currency as the primary amount and the original INR separately. All evidence uses fictional data.

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

### Banking screenshots (Step 2C.1)

The list screenshots use the literal search `transfer`, showing two supplied transfer legs and their separate fee while the account/date-range totals stay unchanged. This is activity filtering, not an interactive matching workflow.

| Activity view | Light | Dark |
| --- | --- | --- |
| Desktop, 1440 px | [Screenshot](screenshots/banking-1440-light.jpg) | [Screenshot](screenshots/banking-1440-dark.jpg) |
| Tablet, 768 px | [Screenshot](screenshots/banking-768-light.jpg) | [Screenshot](screenshots/banking-768-dark.jpg) |
| Mobile, 390 px | [Screenshot](screenshots/banking-390-light.jpg) | [Screenshot](screenshots/banking-390-dark.jpg) |

Transaction inspection: [desktop light](screenshots/banking-inspector-1440-light.jpg), [mobile light](screenshots/banking-inspector-390-light.jpg), and [mobile dark](screenshots/banking-inspector-390-dark.jpg). The [partial-data/error example](screenshots/banking-partial-error-390-dark.jpg) shows SBI source reconciliation with the separate balance retained. All values, labels, and references are fictional.

### Transfer review verification and screenshots (Step 2C.2)

Production-browser review covered unique and competing candidates, confirmation, pair-specific dismissal/restore, unlink and undo, source inspection outside activity filters, exact origin-link focus return, and the shared Overview excerpt. Partial/error/retry retained compatible decisions. USD displays, masking of amounts and references, and the source inspector were checked on mobile. Automated tests additionally cover missing/ineligible source legs, stale actions, underlying manual classifications, exclusive membership, invalid/calendar-boundary dates, empty/reset/reload behavior, and every existing workspace currency surface.

Both themes were checked at 1440, 768, 390, and 320 px without horizontal overflow, including a selected pair and the source inspector at 320 px. Measured non-gradient text contrast remained at least approximately 4.80:1 light and 4.73:1 dark, including warning states. Summary cards reuse the existing hero gradient tokens; muted-text contrast at their endpoints is at least 4.84:1 light and 5.12:1 dark. Structural axe checks passed with the confirmation panel both collapsed and expanded. Production-preview logs contained no warnings/errors, and local asset URLs and security headers were verified. No dependencies changed. The outstanding zoom, screen-reader, and runtime reduced-motion checks above still apply.

| Suggested pair | Light | Dark |
| --- | --- | --- |
| Desktop, 1440 px | [Screenshot](screenshots/transfers-1440-light.jpg) | [Screenshot](screenshots/transfers-1440-dark.jpg) |
| Tablet, 768 px | [Screenshot](screenshots/transfers-768-light.jpg) | [Screenshot](screenshots/transfers-768-dark.jpg) |
| Mobile, 390 px | [Screenshot](screenshots/transfers-390-light.jpg) | [Screenshot](screenshots/transfers-390-dark.jpg) |

Additional evidence: [competing candidates](screenshots/transfers-ambiguous-1440-light.jpg), [explicit mobile confirmation in USD](screenshots/transfers-confirm-390-dark.jpg), [confirmed pairs counted once](screenshots/transfers-confirmed-1440-dark.jpg), and [partial coverage with a retained load error](screenshots/transfers-partial-error-390-dark.jpg). Screenshots use fictional records; tall viewport captures show the queue layout, while the confirmation and error examples show their relevant viewport. Reflow was measured separately at a 1000 px viewport height.

### Category review verification and screenshots (Step 2C.3)

`npm run check` passed all 181 tests across 14 files, TypeScript checking, and the production build. After the final refund-evidence wording and preview cleanup, all 50 affected category/banking component tests, TypeScript checking, and the production build passed again. The new tests cover exact previews and exclusions, stale-source rejection, direction and role restrictions, atomic undo, refund attribution and missing evidence, unchanged source records/balances/assets, privacy, navigation, and demo-state recovery.

Production-browser review exercised individual suggestion acceptance, a mixed bulk selection with two eligible expenses and one excluded credit, shared undo, purchase/refund category propagation, source inspection, INR/USD switching, masking, and retained decisions through partial/error/retry. Both themes were checked at 1440, 768, 390, and 320 px without horizontal overflow; bulk previews and inspectors also fit at 320 px. Measured non-gradient text contrast remained at least approximately 4.80:1 light and 5.84:1 dark. Summary/inspector gradients reuse the existing verified tokens. Structural axe checks passed for the queue, bulk preview, and inspector preview. Actual 400% zoom, full screen-reader testing, and a runtime reduced-motion preference switch remain outstanding as described above.

Production-preview logs contained no warnings/errors. The final build used local script/style assets, and its CSP, frame denial, no-sniff, referrer, and permissions headers were verified. No dependencies changed. Review decisions and financial data remain in memory; only existing display preferences persist.

| Suggestions view | Light | Dark |
| --- | --- | --- |
| Desktop, 1440 px | [Screenshot](screenshots/categories-1440-light.jpg) | [Screenshot](screenshots/categories-1440-dark.jpg) |
| Tablet, 768 px | [Screenshot](screenshots/categories-768-light.jpg) | [Screenshot](screenshots/categories-768-dark.jpg) |
| Mobile, 390 px | [Screenshot](screenshots/categories-390-light.jpg) | [Screenshot](screenshots/categories-390-dark.jpg) |

Additional evidence: [bulk preview with an excluded credit in USD](screenshots/categories-bulk-1440-dark.jpg), [individual correction preview](screenshots/categories-inspector-390-dark.jpg), and [partial coverage with retained reviews and a load error](screenshots/categories-partial-error-390-dark.jpg). All records are fictional. Desktop/tablet captures use tall viewports to show the queue; mobile captures focus on the review controls and suggestions. Reflow measurements used a 1000 px viewport height.

### Monthly budget verification and screenshots (Step 2D.1)

The full `npm run check` run passed 217 tests across 16 files, TypeScript, and the production build. After tightening source-navigation focus and empty-to-partial recovery and adding a no-budgets regression, all 71 affected budget/banking/category/transfer component tests passed, followed by TypeScript and build. A display-rounding note and mobile spacing adjustment were followed by all 12 budget component tests, TypeScript, and production build. A subsequent CSS-only maximum-value wrapping fix passed TypeScript/build and browser reflow checks in INR and USD at 320 px. At this increment the suite contained 218 tests; the added regression is included in those affected runs. No dependencies changed.

Production-browser review exercised invalid limit entry, save and undo, canonical INR editing while reporting USD, masked draft removal/restoration, source inspection and Escape return, purchase/refund category propagation, and retained planning data through partial/error/retry. Both themes fit at 1440, 768, 390, and 320 px without page-wide overflow. Expanded details and narrow editing/source dialogs were checked, including forward/reverse focus wrap. Measured non-gradient text contrast remained at least approximately 4.80:1 light and 5.93:1 dark; existing hero gradient tokens are unchanged. Structural axe checks passed for the workspace, editor, and expanded category. Actual 400% zoom, enlarged text, full screen-reader testing, and a runtime reduced-motion preference switch remain outstanding as described above.

The final build uses local script/style assets. Production response/security headers were verified, and browser logs contained no warnings/errors. Source records and bank snapshots are unchanged. Display conversions use exact original-INR totals before rounding; a USD note explains why independently rounded displayed figures can differ slightly.

| Monthly budgets | Light | Dark |
| --- | --- | --- |
| Desktop, 1440 px | [Screenshot](screenshots/budgets-1440-light.jpg) | [Screenshot](screenshots/budgets-1440-dark.jpg) |
| Tablet, 768 px | [Screenshot](screenshots/budgets-768-light.jpg) | [Screenshot](screenshots/budgets-768-dark.jpg) |
| Mobile, 390 px | [Screenshot](screenshots/budgets-390-light.jpg) | [Screenshot](screenshots/budgets-390-dark.jpg) |

Additional evidence: [USD reporting with an INR limit editor](screenshots/budgets-editor-390-dark.jpg), [masked input and progress](screenshots/budgets-masked-editor-390-dark.jpg), [expense/refund source breakdown in USD](screenshots/budgets-detail-1440-light.jpg), and [retained limits during a partial-data load failure](screenshots/budgets-partial-error-390-dark.jpg). The [maximum-limit example at 320 px](screenshots/budgets-large-limit-320-light.jpg) verifies that large INR values wrap without horizontal overflow. All values are fictional. Tall viewport captures show the layout; reflow measurements used a 1000 px height.

## Cash-flow trends

The Cash flow view inside `#/budgets` covers August, September, and October 2026 for All accounts, HDFC, or SBI. August and September are full months; October stops at 20 October, 10:00 IST. These controls apply only to analytics; October budget limits still cover both accounts. Reload starts with Monthly budgets and default cash-flow controls. Recurring has an independent month selector and review history.

Monthly charts have selectable, keyboard-operable month groups and an always-visible table. Daily charts have a visible zero baseline, negative-spending support, horizontal scrolling, keyboard-operable days, and a disclosure for the equivalent table. Select a month/day or source category to inspect its contributing records. The source list starts collapsed to keep reconciliation accessible. Day/category selection changes that list without redefining the month summary or reconciliation. Source inspection restores the selected view, account, month, day, category, scroll, and exact source link; if a correction removes the link, focus falls back to the source heading. A direct transaction reload opens Banking inspection.

### Historical source evidence

There is one authoritative collection of 58 fictional transactions: 15 August, 15 September, and the unchanged 28 October records. `getBankTransactions` defaults to the October period; an explicit `null` period supplies the full evidence for review, inspection, and period selectors. Banking's default activity and category filters still show October. Date filters expose historical records through the same inspector and category review model. Its balance cards remain explicitly dated October snapshots.

The six independently supplied statements reconcile exactly before local review changes. Monetary values below are original INR; pending entries are excluded.

| Statement | Opening | Posted credits | Posted debits | Closing |
| --- | ---: | ---: | ---: | ---: |
| HDFC August | 87,885.90 | 90,000.00 | 48,400.00 | 1,29,485.90 |
| SBI August | 42,338.80 | 5,230.00 | 4,604.90 | 42,963.90 |
| HDFC September | 1,29,485.90 | 96,500.00 | 48,700.00 | 1,77,285.90 |
| SBI September | 42,963.90 | 240.00 | 5,004.90 | 38,199.00 |
| HDFC October 1–20 | 1,77,285.90 | 95,800.00 | 86,665.90 | 1,86,420.00 |
| SBI October 1–20 | 38,199.00 | 43,250.00 | 6,599.00 | 74,850.00 |

August closings equal September openings, and September closings equal October openings. Statement reconciliation filters by its own account, owner, and period before summing posted movements; adding history cannot inflate October balances. The Overview tracked-asset baseline remains INR 50,86,080.

August adds a supplied investment withdrawal to exercise investment credits. September's `t51` refund of INR 1,500 references August's `t33` purchase of INR 6,000. The credit offsets the purchase's current expense category in September only. A category correction to the purchase propagates to that refund; missing/ineligible evidence or clearing the purchase classification leaves the credit unresolved. The existing October purchase/refund evidence is unchanged. Source inspection and correction previews identify the relevant historical statement and linked purchase/refund.

### Calculations and coverage

| All-account metric, before review changes | August | September | October 1–20 |
| --- | ---: | ---: | ---: |
| Classified income | 90,230.00 | 95,240.00 | 95,250.00 |
| Gross expenses | 41,004.90 | 38,704.90 | 36,764.90 |
| Verified refunds | 0.00 | 1,500.00 | 800.00 |
| Net classified spending | 41,004.90 | 37,204.90 | 35,964.90 |
| Classified surplus | 49,225.10 | 58,035.10 | 59,285.10 |
| Net bank movement | 42,225.10 | 43,035.10 | 45,785.10 |

Every eligible posted entry occupies one effective role. Net bank movement equals classified income minus net spending, plus investment credits minus investment debits, plus confirmed transfer credits minus transfer debits, plus unresolved credits minus unresolved debits. Pending counts and amounts are separate. Classification changes alter the bridge's roles but do not alter source cash movement, statement balances, or assets. A single transfer leg remains in an account/day/month scope when its validated counterpart is outside it; pair validation uses the full collection. Refund-driven negative spending and classified deficits remain signed.

Coverage comes from explicit account/date intervals, never the first/last transaction. Complete source intervals can contain known zero days; dates without supplied history or beyond 20 October remain gaps. A partially covered day without posted evidence shows Not supplied, including a pending-only day. Available amounts with incomplete coverage remain explicitly incomplete. Source completeness and classification completeness are separate: the populated October source period is complete, with six unresolved posted movements and two pending entries.

Partial mode removes only October's SBI bill `t26`. Both historical months remain complete. SBI 1–18 October is complete; 19–20 October is an explicit missing/stale interval. Available October net spending becomes INR 33,764.90 and movement INR 47,985.10, while SBI's supplied closing stays INR 74,850 and statement-minus-calculated difference stays INR −2,200. No artificial adjustment fills this gap.

Comparisons use the same first N calendar days and same account scope. October 1–20 compares with September 1–20; September 1–30 compares with August 1–30. Unsupported July history suppresses August comparisons. Both windows require complete source coverage and no unresolved posted classification; otherwise the view explains why changes are unavailable. A zero prior value has no percentage. Signed changes use current minus prior; percentages use the absolute prior amount. None of these metrics represents savings, disposable income, investment return, a forecast, or a projected balance.

Original INR minor-unit arithmetic is exact. USD uses the existing dated fictional FX rate for display only, including chart axes, tables, comparison differences, sources, bridge, pending values, and statement details. It is not historical FX; independently rounded displayed figures can differ. Masking removes monetary values, percentages, chart geometry, and accessible financial values, retaining neutral chart placeholders and period/category labels. Masked amounts have an explicit accessible role. Filters, disclosures, selections, and review decisions remain in memory; only existing display preferences persist.

Loading hides cash-flow totals. Partial/error/retry retain compatible controls and shared review decisions; errors keep the last usable snapshot. Empty resets cash-flow selections and disclosures, and restoring samples reinstates initial reviews and limits. Reload resets controls, budget edits, and reviews. No dependencies, external services, persistence, backend, real data, or trading capabilities were added.

Implementation: `frontend/src/data/bankHistory.ts` supplies historical records and balances; `banking.ts` owns the combined collection and period-scoped statement reconciliation; `cashFlow.ts` defines coverage, effective roles, aggregation, and comparisons. `CashFlow.tsx` and `cash-flow.css` provide the view. Existing Banking/Budgets, review, money, display, and route helpers supply shared behavior.

### Cash-flow verification and screenshots (Step 2D.2)

The full `npm run check` run passed 243 tests across 18 files, TypeScript checking, and the production build. Subsequent source-disclosure, incomplete-day, and mobile-label refinements passed all 25 cash-flow data/component tests, TypeScript, and the production build. The data checks cover all six statement reconciliations, adjoining balances, known monthly results, every supplied day/account bridge, one-sided and cross-month transfers, refund-driven negative spending, cross-month purchase corrections/undo, missing evidence, pending exclusions, coverage gaps, matching-day comparisons, zero prior values, immutable sources, and unchanged October/Overview baselines.

Component checks cover month/account/day/category selection, keyboard chart operation, table equivalents, source inspection and exact/fallback focus return, Back/Forward, historical direct routes and Banking filters, shared classification updates, INR/USD surfaces, masking of text/attributes/geometry, in-memory state, partial/error/retry/loading/empty/reload, and structural axe checks for normal/table/masked views. The shared masked-value element now has an explicit accessible role. Structural tests disable jsdom's color-contrast rule; its existing canvas-support warning does not replace browser contrast checks.

Production-browser review exercised keyboard selection of the September refund day, the equal-day comparison in USD, historical source provenance, Escape and exact-link focus restoration, masking, partial SBI day gaps, retained account controls during load failure, retry, and the unchanged statement gap. Both themes fit at 1440, 768, 390, and 320 px without page-wide overflow. Daily charts intentionally scroll inside their own region; monthly charts fit the viewport, and tables provide all values. Measured non-gradient text contrast was at least approximately 4.80:1 light and 5.84:1 dark. Hero gradients reuse existing tokens. Actual 400% zoom, enlarged text, a runtime reduced-motion preference switch, and full screen-reader testing remain unverified; the available browser controls expose viewport sizing, not those settings.

The production preview returned HTTP 200 with the existing restrictive CSP, frame denial, no-sniff, referrer, and permissions policies. Browser warning/error logs were empty. Assets remain local, no dependency inputs changed, and financial values, review decisions, and cash-flow controls do not enter storage or URLs.

| Cash flow | Light | Dark |
| --- | --- | --- |
| Desktop, 1440 px | [Screenshot](screenshots/cashflow-1440-light.jpg) | [Screenshot](screenshots/cashflow-1440-dark.jpg) |
| Tablet, 768 px | [Screenshot](screenshots/cashflow-768-light.jpg) | [Screenshot](screenshots/cashflow-768-dark.jpg) |
| Mobile, 390 px | [Screenshot](screenshots/cashflow-390-light.jpg) | [Screenshot](screenshots/cashflow-390-dark.jpg) |

Additional evidence: [September comparison and cross-month refund in USD](screenshots/cashflow-refund-1440-light.jpg), [masked charts](screenshots/cashflow-masked-390-dark.jpg), [retained SBI scope during partial-data load failure](screenshots/cashflow-partial-error-390-dark.jpg), and [single-account bridge and statement gap](screenshots/cashflow-gap-390-dark.jpg). All values and source records are fictional. Tall captures show context; 320 px reflow measurements used a 1000 px viewport height.

## Recurring-expense review

The Recurring view inside `#/budgets` reviews seven supplied monthly patterns across August–October 2026. It shares the existing 58-record ledger, effective classifications, source inspector, and dated reporting FX. No records, source amounts, statement balances, or budget limits were added or changed. All patterns start unconfirmed.

### Supplied evidence and schedules

These definitions are explicit fictional evidence, not inferred contracts or a general detection service. Each pattern binds the same known owner, account, and payee to its original source identities. The day is a supplied schedule; actual dates remain visible and can differ.

| Pattern | Account | Supporting occurrence IDs | Monthly day | Original INR observations |
| --- | --- | --- | ---: | --- |
| Home rent | HDFC | `t30`, `t45`, `t02` | 2 | Fixed 22,000 |
| Electricity | HDFC | `t31`, `t46`, `t03` | 3 | Range 1,700–1,900 |
| Monthly subscription | SBI | `t39`, `t55`, `t23` | 15 | Fixed 499 |
| Water & maintenance | SBI | `t41`, `t57`, `t26` | 19 | Range 2,000–2,200; October source missing in partial mode |
| Monthly service fee | SBI | `t42`, `t58` | 22 | Fixed 5.90; HDFC's separate `t11` fee is unrelated |
| Grocery top-up | HDFC | `t36`, `t50` | 28 | Range 1,800–2,200; regular grocery trips are separate |
| Home purchases | HDFC | `t33`, `t52` | 12 | Range 2,000–6,000; ambiguous October association |

Home purchases has two unassigned October candidates: posted `t07` and pending `t16`. Neither is counted as an October recurring occurrence. Confirmation is disabled because the association is ambiguous; dismissal and restoration remain available. Pending is never treated as paid. The observations are gross source expenses; purchase refunds remain separate in the existing actual-spending calculations.

Confirming both the service fee and grocery top-up produces a fixed expected total of **INR 5.90**, plus a separately shown **INR 1,800–2,200 range**, for 21–31 October. The range is not averaged or added to the fixed total. Confirmed rent/subscription/bills already recorded this month do not become another expected payment. Historical months show evidence only. A monthly day beyond month end clamps to the last day without changing the original day for subsequent months; leap years and century boundaries are covered by tests.

### Review, integrity, and coverage

Expand a pattern to inspect its source dates, amounts, payee, monthly interval, and eligibility. Confirm recurring, Dismiss suggestion, Restore suggestion, Undo recurring change, and Reset sample recurring decisions operate on a dedicated in-memory history. Filters show all, suggested, confirmed, or dismissed patterns; changing the month does not change budget or cash-flow controls. A confirmed pattern may be dismissed, and undo restores the previous decision. Reset affects only recurring decisions; category/transfer reviews and budget limits retain their own histories.

Confirmation revalidates full source identity (including payee/narrative), known ownership, positive original INR debit amounts, eligible posted expense roles, distinct monthly occurrences, and non-overlapping source membership. Duplicate IDs, reused occurrences, same-month café repeats, altered source evidence, and stale action evidence cannot establish a pattern. Pending, transfers, investments, refunds, and unresolved movements are excluded. An expense-to-expense category correction remains compatible; unresolved or retained transfer membership invalidates the affected evidence. Undo or restoration of valid source evidence can make a retained confirmation usable again.

Changed or missing evidence retains the decision with **Needs review** and excludes it from expectations. Partial mode removes `t26`: maintenance retains its confirmation but its October occurrence becomes **Unknown**. Available observations still show their actual source amounts. The incomplete SBI coverage also withholds the future service fee from expected totals; HDFC's supported grocery pattern remains eligible. Expected totals are a subset of reviewed patterns, never an assurance of complete upcoming expenses.

Occurrence states distinguish **Recorded**, **Pending source**, **Expected**, **Not observed in available records**, **Unknown**, **Needs review**, and **Unconfirmed**. Absence is only labeled not observed when the relevant supplied account window is complete; missing history is not evidence of nonpayment. Expected entries never create transactions, change bank snapshots, or enter actual spending, budget remaining, or cash-flow totals. All previously documented accounting baselines remain unchanged.

### State, navigation, and privacy

The month, filter, expanded pattern, decisions, and undo history stay in memory. Loading hides totals/actions; partial and failed-load states retain compatible decisions and the last usable sources. Retry does not duplicate decisions. Empty clears recurring decisions and controls; restoring samples returns the initial fixtures. Reload resets all recurring state and preserves only display preferences.

Source links open the shared transaction inspector and return to Recurring with its month, filter, expansion, scroll, and source-link focus. Back/Forward preserve the session origin; when a source disappears, focus falls back to the pattern-list heading. A directly loaded transaction URL still opens in Banking. No month, decision, amount, or evidence key is placed in the URL or browser storage.

All source amounts, observed ranges, expected entries, and totals follow INR/USD. Masking removes monetary content from the DOM and accessible values, including both endpoints of a range and inspector narration/reference. Status messages contain no financial amounts. Source text renders as text, without HTML interpretation. There are no new dependencies, network calls, provider credentials, file inputs, backend services, notifications, schedulers, payment actions, or persistence.

Implementation: `frontend/src/data/recurring.ts` defines supplied evidence, validation, reversible decisions, calendar dates, occurrence states, and exact totals. `RecurringReview.tsx` and `recurring.css` provide the view; App/Budgets own independent state and existing routes provide source inspection.

### Recurring verification and screenshots (Step 2D.3)

- Full `npm run check`: **299 tests across 20 files passed**, with TypeScript checks and production build. The 56 recurring data/component tests also passed after copy refinements; the final wording/disclosure-style changes passed TypeScript/build and browser verification. The suite emits existing jsdom canvas-implementation notices; real browser checks supply layout and contrast evidence.
- Data coverage includes original identity changes, known ownership, eligibility exclusions, duplicate/overlapping occurrences, stale decisions, independent undo/reset, missing sources, classification changes/undo, exact fixed/range separation, historical months, month-end/leap-year dates, unsupported inputs, and unchanged ledger, balances, budgets, cash flow, and assets.
- Component checks cover review actions/filters, source correction and focus return, pending/ambiguous candidates, partial/loading/error/retry/empty/reload, INR/USD across monetary surfaces, masked DOM/storage boundaries, plain-text rendering, keyboard actions, and automated axe checks in expanded light and masked dark states.
- Production browser checks cover both themes at **1440, 768, 390, and 320 px** without page overflow; mobile source details, USD/masking, keyboard focus containment, Escape, real Back/Forward, fixed/range confirmations, partial-source retention, failed-load/retry, loading, and empty recovery. Minimum measured non-gradient text contrast was **4.80:1 light / 5.93:1 dark**, with no measured failures. Primary review and source controls have at least 44 px height. Full screen-reader validation, actual 400% browser zoom/enlarged-text testing, and runtime reduced-motion emulation remain unperformed; 320 px reflow is not a substitute for those checks.
- The local production response returned HTTP 200 with the existing restrictive CSP, frame denial, no-sniff, referrer, and permissions policies. Browser warning/error logs were empty. Dependency manifests/lockfile are unchanged. The final diff was reviewed for source mutation, financial double counting, privacy leaks, unrelated changes, credentials, and attribution text.

Screenshots use fictional fixtures, with selected review decisions applied locally:

- [Light desktop](screenshots/recurring-light-desktop.jpg) and [dark desktop](screenshots/recurring-dark-desktop.jpg).
- [Light evidence](screenshots/recurring-light-evidence.jpg) and [partial evidence](screenshots/recurring-light-partial-evidence.jpg).
- [Light tablet](screenshots/recurring-light-tablet.jpg) and [dark tablet](screenshots/recurring-dark-tablet.jpg).
- [Light mobile](screenshots/recurring-light-mobile.jpg), [dark mobile evidence](screenshots/recurring-dark-mobile-evidence.jpg), and [masked dark 320 px](screenshots/recurring-dark-masked-320.jpg).

## Connections and source coverage (Step 2E.1)

Connections is available at `#/connections`. Sources opens six inline inspectors; Sample imports opens the bank catalog introduced in Step 2E.2 and the investment examples added in Step 2E.4. Literal source/account search is capped at 80 characters, with investment/bank filters and an explicit clear action. Source selection, filters, scenarios, and scroll survive navigation in memory. Closing an inspector restores focus to its source button; browser Back/Forward uses the shared route behavior. Unknown source paths and batch IDs remain unavailable. No source/account, search, decision, or permission value enters the route.

### Financial coverage

Coverage is derived from the existing holdings, bank snapshots, and banking coverage intervals. It is independent of the simulated connection state. Source group, sample account, and individual data streams have separate labels. All six sources say **Bundled sample · No provider connected**. Actual automatic access, permissions, and export formats remain unverified; a display-only UI does not prove a provider has read-only scopes.

| Source | Supplied evidence | Gaps and partial-state behavior |
| --- | --- | --- |
| INDmoney India | Holdings 20 Oct 2026, 17:30 IST; prices/NAV 18:00 IST | Selected activity only; no complete statement period. Broker cash has no independent timestamp. |
| INDmoney US | Holdings 20 Oct 2026, 09:00 IST; quotes 01:30 IST | Selected activity only; no complete statement period. Broker cash has no independent timestamp. |
| Advisor mutual funds | Regular-plan holdings 18 Oct 2026, 10:00 IST; NAV 20 Oct, 18:00 IST | Partial mode removes the NAV, excluding that holding from valued totals. Separate cash was never supplied. |
| UBS Accenture ESPP | Holdings 20 Oct 2026, 09:00 IST; quotes 01:30 IST; selected employee lots | Partial mode retains stale 17 Oct holdings with 20 Oct quotes. Separate cash and complete tax-basis/history are not supplied. |
| HDFC | Full August and September statements; October activity and balance through 20 Oct, 10:00 IST | October is month-to-date. Later activity is never supplied. |
| SBI | Full August and September statements; October balance through 20 Oct, 10:00 IST | Partial mode retains the balance but activity is dated 19 Oct, 10:00 IST; 19–20 Oct coverage is incomplete with a missing bill. |

FX remains separately dated 20 October and display-only. No new monetary surface is introduced; the shared currency/privacy controls and masked FX footer remain intact. Snapshot, full-month, month-to-date, missing stream, stale evidence, and never-supplied data are distinct. Empty source history is not a zero balance. A receipt cannot advance these financial dates.

### Local status and recovery examples

Only INDmoney India/US expose connector simulations; their defaults are Available snapshot and Transient failure, respectively. HDFC, SBI, UBS, and advisor funds are statement examples with no invented authorization or refresh controls. HDFC/SBI source details also link to their bundled bank previews; investment import examples remain planned.

| Scenario | Initial outcome | Explicit recovery/result |
| --- | --- | --- |
| Available snapshot | Sample received | Run sample refresh → In progress → Show sample outcome. Snapshot coverage stays unchanged. |
| Never received | No attempt or receipt | Run/Show creates only a walkthrough receipt; existing financial fixtures were independently available throughout. |
| Stale / partial success | Partial sample received | Run/Show retains 17 Oct, 09:00 IST holdings and a missing activity stream in the walkthrough receipt. It does not alter the portfolio's coverage. |
| Transient failure | Failed attempt with prior receipt | Retry/Show produces the supplied success and preserves financial evidence dates. |
| Rate limited | Deferred attempt with prior receipt | Simulate retry window enables Retry/Show. No countdown, timer, scheduled retry, or network request exists. |
| Expired / revoked access | Access blocked with prior receipt | Simulate access renewal enables Retry/Show. Renewal alone does not turn the last blocked attempt into a success or grant real access. |

All walkthrough timestamps are supplied fixtures on **20 Oct 2026**: initial attempt **19:00 IST**; retained receipt after failure/block/rate limit **18:45 IST**; next attempt **19:05 IST**; next successful receipt **19:06 IST**. Successful initial examples use a 19:00 receipt. Receipt holdings/quote dates remain separate; no machine clock is used. The stale/partial receipt is explicitly separate example evidence, with 17 Oct holdings and each account's original 20 Oct quote date, no activity stream, and no statement period.

In-progress is an explicit walkthrough step. Run and scenario selection are disabled while it is active; Show sample outcome advances it and Cancel sample attempt stops it. No background process completes work. A finished scenario cannot append another attempt until a scenario is loaded or connections are reset. Cancellation rejects late completion and permits a fresh bounded retry. The latest three completed/cancelled outcomes form an explanatory sample history, not a provider audit log. Keyboard focus advances to the next relevant control when a step removes or disables the current button.

### Isolation and recovery

The connection reducer accepts only known connector IDs and scenario/action choices. It cannot write holdings, bank records, prices, source coverage, transfer/category decisions, budget limits, or recurring decisions. Reset sample connection states affects this domain only. All source text renders as text; there are no file inputs, passwords, provider login, credential forms, external assets, requests, exports, parsers, schedulers, backend services, or new dependencies.

Populated/partial states preserve compatible scenarios while coverage follows the financial fixtures. Loading hides source data/actions and cancels pending attempts, retaining completed scenarios and prior receipts. Failed load retains the last usable snapshot and scenarios; retry restores that state without creating receipts. Failed load after empty explicitly has no prior accounts. Empty/reload clears connection scenarios, filters, and selection; restoring samples reinstates defaults. Only theme, currency, and amount visibility persist.

Implementation: `frontend/src/data/connections.ts` contains coverage derivation and isolated state transitions; `Connections.tsx` and `connections.css` provide the view. App owns the connection state separately from financial review domains. The existing router adds only the allowlisted Connections destination.

### Connection verification and screenshots

- Full regression run: **320 tests across 22 files passed** using `node node_modules/vitest/vitest.mjs run --maxWorkers=2`. The initial unrestricted parallel run exceeded several existing UI test time limits; bounded concurrency passed without increasing timeouts. TypeScript and the production build passed. The 21 connection data/component tests were rerun after final keyboard refinements.
- Tests cover all supplied scenarios, retained dates, authorization/retry gates, statement-only sources, no overlapping attempts, cancellation/late completion, bounded history, unknown IDs/enums, literal search, direct/invalid routes, navigation/focus, global states, independent resets, display preferences, privacy, no fetch calls, and automated axe structural checks.
- Financial invariants cover full/partial assets (INR 5,086,080 / 4,661,080), holdings, all six bank reconciliations, financial coverage, existing category decisions, edited budget limits, cash flow, and confirmed recurring expectations across every walkthrough scenario/reset. Connection reset also preserves recurring decisions and budget/cash-flow actuals in component navigation tests.
- Production browser checks passed at **1440, 768, 390, and 320 px in both themes**, including expanded source/recovery views without horizontal overflow. Keyboard renewal → run → outcome moves focus to the next control; close returns to the source. Mobile drawer focus wraps and Escape returns to its trigger. Actual Back/Forward retains the source/scenario; loading cancels attempts, error/retry retains evidence, and empty recovery restores defaults. USD/masking leaves no amounts in rendered text or accessible attributes.
- Minimum measured non-gradient text contrast was **4.80:1 light / 5.84:1 dark**, with no measured failures. Source, scenario, recovery, and history controls have at least **44 px** height at mobile widths. Full screen-reader validation, actual 400% browser zoom/enlarged-text testing, and runtime reduced-motion emulation remain unperformed; narrow-width reflow is not a substitute.
- Loopback production response returned HTTP 200 with restrictive CSP, frame denial, no-sniff, referrer, and permissions policies. Browser warning/error logs were empty. Dependency manifests and lockfile are unchanged. The final recovery-copy refinement passed the nine component tests, TypeScript, and build.

Screenshots show only fictional fixtures:

- [Light desktop](screenshots/connections-light-desktop.jpg) and [dark desktop](screenshots/connections-dark-desktop.jpg).
- [Dark recovery step](screenshots/connections-dark-recovery.jpg) and [light SBI coverage](screenshots/connections-light-bank-coverage.jpg).
- [Light tablet](screenshots/connections-light-tablet.jpg) and [dark tablet](screenshots/connections-dark-tablet.jpg).
- [Light mobile](screenshots/connections-light-mobile.jpg), [dark mobile recovery](screenshots/connections-dark-mobile-recovery.jpg), and [masked dark 320 px](screenshots/connections-dark-masked-320.jpg).

## Bank sample import previews (Step 2E.2)

Connections → Sample imports offers seven HDFC/SBI examples. Each has a stable allowlisted route such as `#/connections/imports/i03`, fictional source metadata, statement and balance dates, an explicit comparison baseline, and a fixed row set. HDFC/SBI source details also open a relevant sample. No file is selected, parsed, or imported. The [sample reference](import-samples.md) supplies independent expected row counts, native totals, and balances for every scenario.

### Evidence and arithmetic

Each row receives exactly one of New candidate, Already present, Duplicate within batch, Possible overlap, Conflict, or Invalid / unsupported. Incoming occurrence IDs are stable independently of source transaction IDs and list order. Source identities include provider, owner, and account. Identical copies point to a deterministic canonical row; conflicting immutable fields retain both versions. Same-date/payee/amount similarity with a different identity stays unresolved rather than proving a duplicate. Batch fingerprint labels and row matches are separate checks.

Original source totals include every readable occurrence, including duplicates and rows with other validation errors. They are grouped by original currency and posting status. The separate new-candidate subset excludes already-present, duplicate, and unresolved rows; it is not a final import effect. Source arithmetic uses the full original posted set and exact native minor units. Missing balances, unreadable money/status/direction, and mixed original currencies keep arithmetic unavailable. Matching opening/closing arithmetic does not imply complete coverage or readiness. No reconciliation adjustment is manufactured.

The row inspector explains the disposition and shows normalized values, original supplied text, and matched baseline/conflicting evidence. Ambiguous dates are not guessed; malformed money remains unavailable. Original text, including a hostile fictional HTML example, renders as text. There are no include/skip/map/correct/complete controls.

### Navigation, privacy, and isolation

Catalog bank/search filters and per-batch disposition/account/search filters stay in memory through navigation. Filtering never changes whole-batch counts, totals, or reconciliation. Inspect rows jumps to the row list. The inspector traps focus, supports Escape, and returns focus to the row or list heading when a canonical row is outside the active filter. Back to sample imports/source restores its originating control and scroll position; browser Back/Forward preserves per-batch selection. Only allowlisted batch IDs enter the route. Reload resets all import controls.

INR/USD changes every primary amount, including native-group summaries, source balances/differences, rows, and normalized comparison evidence. Original currency remains labeled, and original supplied amount text is unchanged. Masking removes descriptions, all original fields, searches, and matching financial text from rendered DOM/attributes/accessibility labels; normalized amounts use the shared mask. Only display preferences persist.

Loading closes inspection and hides financial previews/actions while retaining filters. Empty clears import controls; restoring samples starts fresh. Failed load retains the last usable view. Partial mode explicitly retains each isolated comparison baseline, independently of the partial portfolio. Connection resets cannot alter import controls; previews cannot change bank/holding records, source dates, transfer/category decisions, budgets, cash-flow results, or recurring expectations. This is a local inspection model, not production parsing, authentication, authorization, durable idempotency, or an audit log.

Implementation: `frontend/src/data/imports.ts` supplies isolated fixtures, validation, identity comparisons, exact arithmetic, and filters. `ImportPreview.tsx` and `imports.css` provide the catalog, preview, and inspector. App owns only ephemeral controls; `routes.ts` allowlists batch paths. No dependency, backend, database, migration, or deployment change is introduced.

### Import verification and screenshots

- Data validation: 47 import tests verify the seven independent row partitions, native posted/pending amounts, source balances/differences, replay versus row identity, deterministic duplicate selection, conflicting versions, invalid fields, literal filters, immutable fixtures, and unchanged full/partial financial baselines. Twelve import component tests cover routes, catalog/source entry, filters, inspection, focus/history, USD originals, masking, hostile text, lifecycle states, independent resets, and structural accessibility. Nine existing connection tests also passed with the new tab.
- All **379 distinct tests across 24 files** were verified through the full regression run and targeted reruns. The initial standard-worker run (`--maxWorkers=1 --testTimeout=30000`) recorded 366 passes, three timeouts, a follow-on transfer query failure, and a worker-start timeout that prevented nine recurring tests from running. All 50 tests in the affected currency, holding-detail, transfer, recurring, and import UI files subsequently passed with `--pool=vmThreads --maxWorkers=1 --testTimeout=30000`. The VM retry exposed two cross-realm snapshot comparisons in the new data tests; those snapshots now compare exact BigInt values and Set members, and all 47 import data tests passed again. This is validation across multiple runs, not a single green full-suite run. Repository timeout settings are unchanged. TypeScript, the production build, staged whitespace checks, and local documentation links passed.
- Browser checks covered 1440, 768, 390, and 320 px in Indigo & Apricot light/dark themes. Catalog, previews, filters, original/matched inspection, and narrow layouts had no observed horizontal overflow. Import controls have at least 44 px height. The row shortcut, Tab/Shift+Tab containment, Escape/close focus, actual Back/Forward, loading/empty/error/partial states, USD values, and masked source text were checked.
- Minimum measured non-gradient text contrast was 4.80:1 light / 5.84:1 dark, with no measured failures. Automated axe checks found no structural violations in preview and visible/masked inspection. Full screen-reader validation, actual 400% browser zoom/enlarged-text checks, and runtime reduced-motion emulation remain unperformed; narrow reflow is not a substitute.
- Original HTML-like text rendered literally with no injected image/script nodes. Masking removed source descriptions, original fields, matching financial values, search text, and financial accessible attributes. Browser warning/error logs were empty. Local HTTP returned 200 with restrictive CSP, frame denial, no-sniff, referrer, and permissions policies. Dependency manifests and lockfile are unchanged.

Screenshots show fictional examples only:

- [Light catalog](screenshots/imports-catalog-light-desktop.jpg), [light preview](screenshots/imports-preview-light-desktop.jpg), [dark USD preview](screenshots/imports-preview-dark-desktop.jpg), and [dark row inspection](screenshots/imports-inspector-dark-desktop.jpg).
- [Light tablet](screenshots/imports-preview-light-tablet.jpg) and [dark tablet](screenshots/imports-preview-dark-tablet.jpg).
- [Light mobile inspection](screenshots/imports-inspector-light-mobile.jpg), [light 320 px preview](screenshots/imports-preview-light-320.jpg), and [masked dark 320 px inspection](screenshots/imports-inspector-dark-masked-320.jpg).


## Reversible bank review (Step 2E.3)

The seven bank samples now support an independent import-review history. Open an incoming row to include a valid candidate, skip an exact existing record or repeated occurrence, exclude it with a fixed source-review reason, or restore its undecided state. Every choice has a consequence preview and cancel action. Original evidence and matching versions remain inspectable. The i03 café overlap can be included only because its supplied annotation and distinct source references establish separate payments; similarity alone cannot justify skipping either payment.

**Review suggested choices** previews an atomic set of decisions for untouched valid new records and exact matches/copies. Existing choices remain intact, and possible overlaps still require individual inspection. Each choice retains its source, matched evidence, reason, and prior choice; the independent history supports Undo review change and Reset sample import reviews. Excluded counts include skipped within-batch copies. Exclusions can resolve a review choice while leaving financial/source blockers unresolved. The only compatible mapping in these fixtures is the supplied bank account; incompatible owner/provider/account records cannot be repaired through arbitrary mapping or field edits.

Source-statement arithmetic and retained-baseline-plus-unique-candidates reconciliation are separate. Both use exact native minor units, the same account/currency/period, independently supplied balances, and posted movements; pending movements remain separate. Every required source identity must be represented even when omitted amounts would cancel to zero. Invalid or conflicting records, missing balances/coverage, ambiguous baseline identities, or unexplained differences block completion. Filters and display FX never change these checks. [Fixture expectations](import-samples.md#reversible-review-expectations-step-2e3) describe the seven outcomes.

The final preview shows included/present/excluded/unresolved counts, reasons, native proposed movements, source arithmetic, combined reconciliation, coverage, and the sample-only effect. Completion records one in-memory receipt for the current revision and decision set: **Sample only — no records saved**. Repeated confirmation creates no additional receipt or history entry. A completed review must be explicitly reopened before editing; reopening removes its current receipt. Set sample aside keeps the choices but disables completion until reopened. Undo can restore an earlier compatible completion state.

Actions bind the complete source and baseline evidence, revision, mapping, current decisions, operation, and session revision. Confirmation revalidates that token; stale actions fail atomically with a safe message. Changed evidence leaves prior choices visible as Needs review and suppresses incompatible receipts. Restore/review again or reset starts fresh. These are in-memory consistency checks, not production hashing, authorization, durable idempotency, or audit records.

INR/USD applies to the review, row-action preview, final summary, and receipt-associated totals with labeled native originals. Masking removes pending amount-affecting previews and receipt details, hides original/monetary text, and disables changes/completion. Explicit undo and reset remain available. Loading unmounts action previews and inspectors, preserves draft decisions, and hides values; empty resets import state. Partial and failed-load states retain compatible decisions and fixed sample evidence. Reload clears decisions, receipts, history, filters, and selection. Only existing display preferences persist. Connection resets, financial reviews, and import resets remain independent.

Implementation: `data/import-review.ts` owns pure decision/reconciliation/history transitions; `ImportReview.tsx` supplies summary and row-choice controls; App owns the ephemeral state. No dependency, API, provider connection, parser, file input, database, migration, credential flow, or deployment is added.

### Review verification and screenshots

- The full regression run passed **415 tests across 26 files** with standard workers (`--maxWorkers=1 --testTimeout=30000`). A final affected run covers **96 tests**, including one additional missing-row invalidation case: **416 distinct tests verified**. All eight review UI tests also passed after the final empty-state reset guard, which preserves the session revision to reject older action tokens. The 29 decision tests cover all seven expected outcomes, stale evidence/operations/choices, same-day repeats, duplicate exclusivity, conflicting/invalid data, source omissions including pending/net-zero cases, receipt idempotency, reopen/undo/reset, and immutable evidence. Eight new UI tests cover confirmation/cancel, overlap/exclusion, independent resets, masking, currencies, lifecycle states, and structural accessibility. Existing full/partial invariants now execute import changes and confirm unchanged assets, holdings, all six bank reconciliations, budgets, cash flow, transfer/category state, and recurring results.
- TypeScript and the production build pass. Vite reports the current single JavaScript bundle at approximately 515 kB minified / 144 kB gzip, above its 500 kB advisory threshold. Route splitting remains a performance follow-up; the warning threshold is unchanged. No package or lockfile changes. Automated axe checks found and prompted correction of duplicate preview landmark labels; final checks report no structural violations. jsdom emits its existing canvas capability warning during axe checks.
- Browser checks cover 1440, 768, 390, and 320 px, light/dark, native and USD display, choice and completion confirmations, cancel, reopen, keyboard focus, Escape, and masked content. No observed horizontal overflow; new controls meet 44 px height. Measured non-gradient text contrast remains at least 4.80:1 light / 5.84:1 dark. Browser warning/error logs are empty. Actual screen-reader validation, enlarged-text/400% browser zoom, and runtime reduced-motion emulation remain unperformed; 320 px reflow does not substitute for them.
- Tests verify no import network requests, no financial review persistence, and no financial values in routes. Browser inspection confirms masking removes monetary markup and dismisses pending choice previews. Local HTTP returns 200; existing restrictive preview headers remain in place. Documentation links and whitespace are checked before the commit.

Fictional screenshots:

- [Light desktop choice](screenshots/import-review-choice-light-desktop.jpg), [light completed review](screenshots/import-review-completed-light-desktop.jpg), and [dark USD completed review](screenshots/import-review-completed-dark-desktop.jpg).
- [Dark tablet confirmation](screenshots/import-review-confirm-dark-tablet.jpg), [light mobile choice](screenshots/import-review-choice-light-mobile.jpg), [light 320 px completion](screenshots/import-review-confirm-light-320.jpg), and [masked dark 320 px inspection](screenshots/import-review-masked-dark-320.jpg).

## Investment statement walkthroughs (Step 2E.4)

Connections → Sample imports now offers fourteen examples, with source and bank/investment filters. Seven new allowlisted routes (`i08`–`i14`) cover Indian holdings/cash, US fractional holdings, one folio in two sources, advisor regular funds, UBS employee shares, incompatible fields, and a bounded purchase history. All six source inspectors link to a relevant example. The [sample reference](import-samples.md#investment-sample-expectations-step-2e4) records independent partitions, units, money, and expected completion outcomes.

Every record has an explicit meaning: position snapshot, supported purchase/sale activity, cash balance/dividend, or remaining lot. Inspection shows normalized interpretation alongside escaped original fields. Units retain eight-place precision; quotes retain six and native money two. Unsupported precision, kind-specific extra fields, unknown identities, incompatible plans/folios, invalid calendar dates, or inconsistent dividend components stay invalid. Quotes and positions retain their independent instants. Missing quotes permit only a narrowly scoped position review with valuation unavailable. No values are filled with zero unless zero is supplied.

Snapshot identity includes owner, account, instrument, scheme, plan, option, form, folio, and instant. The identical i10 Direct/Growth position appears through INDmoney and a consolidated comparison. Use incoming snapshot or Keep comparison snapshot retains exactly one position with no new units or cash, and records only that identity/date preference. Conflicting values cannot be overridden. The advisor Regular fund remains separate from Direct, and ACN at INDmoney US remains separate from UBS ownership.

Review suggested choices previews untouched valid candidates and exact-copy skips; overlaps require individual decisions. Choices can be canceled or restored, samples set aside/reopened, and completion requires a final scoped preview. Bank and investment reviews share ordered undo/reset, while financial and connection domains stay independent. In-memory receipts require compatible current source/baseline evidence, revision, mapping, prior choices, operation, and session serial. Stale confirmations fail atomically; repeated completion does not duplicate history. Reopen clears the receipt before edits.

Supplied checks and selected-plus-comparison checks are distinct. Every necessary identity must be retained and covered by an independent position/cash checkpoint. Activity examples reconcile opening units plus supported movements to closing units, and independently reconcile opening cash plus native cash movements to closing cash. Snapshot-only completion establishes its limited identity/position scope; it does not assert complete transactions, lots, tax basis, or full-account coverage. In i12, the three remaining lots sum to 24 UBS units, yet absent opening history, cash checkpoints, fees, and basis keep completion blocked. i14 explicitly supplies fictional opening units, opening/closing cash, and a zero purchase fee for its bounded interval; these are additional demonstration evidence, not reconstructed account history.

Marked values, cash snapshots, purchase/sale cash, lot purchase amounts, fees, supplied basis, gross dividends, withholding, and net dividends appear in separate native groups. They are never added into one misleading total. INR/USD changes display only; original native reconciliation, units, source dates, and financial baselines remain unchanged. Unknown components show unavailable or a labeled known subtotal.

Search is literal and capped at 80 characters; filters do not affect whole-sample checks. Inspector dialogs contain keyboard focus, close with Escape, and return focus to the triggering row or record heading when a canonical row lies outside the current filter. Source/catalog return links and browser history retain compatible filters and selection. Loading dismisses pending work/inspection but retains drafts; partial/failed load preserves compatible evidence; empty/reload resets local reviews. Privacy hides monetary content, units, quotes, raw strings, source descriptions, searches, pending changes, and receipt details, and disables amount-affecting choices. Undo and reset remain available. Only theme, currency, and masking preferences persist.

Implementation: `data/investment-imports.ts` supplies typed fixtures and validation; `data/investment-review.ts` owns exact checks and pure decisions; `InvestmentPreview.tsx` supplies inspection and review. The shared import model retains both bank and investment snapshots for undo. No dependency, parser, upload, provider API, credential flow, backend, database, migration, or deployment is introduced.

### Investment verification and screenshots

- Full regression: **477 tests across 28 files passed** using standard workers (`--maxWorkers=1 --testTimeout=30000`). Final affected checks passed **150 tests across five files**, including one additional regression for activity history outside the catalog account: **478 distinct tests verified**. The 52 investment data/review cases cover exact values, identity, duplicate cash, fund preferences, precision, missing history/checkpoints, exclusions, stale actions, receipt replay, shared undo/reset, and immutable evidence. Ten investment component tests cover navigation, inspection, choices, masking, display currency, lifecycle states, and structural accessibility. Full/partial financial invariants now execute bank and investment decisions and confirm unchanged assets, holdings, reconciliations, budgets, cash flow, and other review domains.
- TypeScript and production build pass. The unchanged dependency tree reports **zero known vulnerabilities** from `npm audit`. No package or lockfile changes. The single JavaScript bundle is approximately **567 kB minified / 157 kB gzip**, above Vite's existing 500 kB advisory. Route splitting remains a performance follow-up; the warning is not suppressed.
- Browser verification covered all seven investment samples, source/catalog entry and return focus, browser Back/Forward, choices/cancel, completion, native Escape, fractional units, independent cash/position checks, USD originals, unsupported text rendering, and privacy. Partial/failed-load states retain compatible receipts; loading hides inspection and empty restores a fresh review. Desktop/tablet/mobile checks at 1440, 768, 390, and 320 px in Indigo & Apricot light/dark showed no horizontal overflow. Measured controls meet 44 px height. Visible non-gradient text checks found no failures, with minima of 4.81:1 light and 5.85:1 dark. Browser warning/error logs are empty.
- Automated axe checks report no structural violations in source choice, masked inspection, and completion previews. The test environment emits its existing canvas capability warning. Actual screen-reader validation, enlarged text/400% browser zoom, and runtime reduced-motion emulation remain unperformed; narrow-width reflow does not substitute for them.
- Local HTTP returns 200 with the existing restrictive CSP, `nosniff`, and `no-referrer` headers. Tests and source review verify no import requests or financial persistence; only the three display preferences are stored. Self-review covers exact arithmetic, identity/checkpoint completeness, stale-action rejection, cross-domain undo, privacy, safe text rendering, and scope boundaries. Documentation links and diff whitespace are checked before the commit.

Fictional screenshots:

- [Light desktop catalog](screenshots/investment-imports-catalog-light-desktop.jpg), [light source preference](screenshots/investment-imports-preference-light-desktop.jpg), and [dark USD employee-share review](screenshots/investment-imports-ubs-dark-desktop.jpg).
- [Dark tablet completion](screenshots/investment-imports-completed-dark-tablet.jpg), [light mobile completion](screenshots/investment-imports-completed-light-mobile.jpg), [dark mobile lot inspection](screenshots/investment-imports-lot-dark-mobile.jpg), and [masked mobile inspection](screenshots/investment-imports-masked-dark-mobile.jpg).

## Next stage

The import and connection prototype increments are complete. The next work is planning the secure application foundation described in the [project plan](plan.md): Python backend, local PostgreSQL, authentication/authorization, and deployment boundaries for Supabase. Real statements, provider credentials, and execution remain outside the prototype. No next-stage implementation is included here.
