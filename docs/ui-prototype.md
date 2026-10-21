# Frontend prototype

Step 2A provides the local Overview screen and frontend foundation. Steps 2B.1 and 2B.2 add investment holdings and details; Steps 2C.1–2C.3 add banking activity, inspection, transfer matching, and category corrections. Step 2D.1 adds monthly category budgets. All financial records, dates, and exchange rates are fictional. Overview, Investments, Banking, and Budgets are available through navigation; other destinations are visibly marked **Soon** and are not interactive links.

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

`#/budgets` provides an October 2026 plan across both HDFC and SBI, with eight supplied INR limits and all ten expense categories. Full-month limits are compared with available posted activity through 20 October, 10:00 IST, without proration. Utilities and Health initially exceed their limits, Housing and Subscriptions exactly match, Health has an explicit zero target, and Bank fees/Other expense have no limit. Over-limit categories appear first, with stable taxonomy order otherwise. Cash flow and Recurring are labeled Planned; there is no historical month selector yet.

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
| `npm run check` | Passed: 217 tests across sixteen files, TypeScript checks, production build; subsequent affected checks are recorded under Step 2D.1 below |
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

The full `npm run check` run passed 217 tests across 16 files, TypeScript, and the production build. After tightening source-navigation focus and empty-to-partial recovery and adding a no-budgets regression, all 71 affected budget/banking/category/transfer component tests passed, followed by TypeScript and build. A display-rounding note and mobile spacing adjustment were followed by all 12 budget component tests, TypeScript, and production build. A subsequent CSS-only maximum-value wrapping fix passed TypeScript/build and browser reflow checks in INR and USD at 320 px. The current suite contains 218 tests; the added regression is included in those affected runs. No dependencies changed.

Production-browser review exercised invalid limit entry, save and undo, canonical INR editing while reporting USD, masked draft removal/restoration, source inspection and Escape return, purchase/refund category propagation, and retained planning data through partial/error/retry. Both themes fit at 1440, 768, 390, and 320 px without page-wide overflow. Expanded details and narrow editing/source dialogs were checked, including forward/reverse focus wrap. Measured non-gradient text contrast remained at least approximately 4.80:1 light and 5.93:1 dark; existing hero gradient tokens are unchanged. Structural axe checks passed for the workspace, editor, and expanded category. Actual 400% zoom, enlarged text, full screen-reader testing, and a runtime reduced-motion preference switch remain outstanding as described above.

The final build uses local script/style assets. Production response/security headers were verified, and browser logs contained no warnings/errors. Source records and bank snapshots are unchanged. Display conversions use exact original-INR totals before rounding; a USD note explains why independently rounded displayed figures can differ slightly.

| Monthly budgets | Light | Dark |
| --- | --- | --- |
| Desktop, 1440 px | [Screenshot](screenshots/budgets-1440-light.jpg) | [Screenshot](screenshots/budgets-1440-dark.jpg) |
| Tablet, 768 px | [Screenshot](screenshots/budgets-768-light.jpg) | [Screenshot](screenshots/budgets-768-dark.jpg) |
| Mobile, 390 px | [Screenshot](screenshots/budgets-390-light.jpg) | [Screenshot](screenshots/budgets-390-dark.jpg) |

Additional evidence: [USD reporting with an INR limit editor](screenshots/budgets-editor-390-dark.jpg), [masked input and progress](screenshots/budgets-masked-editor-390-dark.jpg), [expense/refund source breakdown in USD](screenshots/budgets-detail-1440-light.jpg), and [retained limits during a partial-data load failure](screenshots/budgets-partial-error-390-dark.jpg). The [maximum-limit example at 320 px](screenshots/budgets-large-limit-320-light.jpg) verifies that large INR values wrap without horizontal overflow. All values are fictional. Tall viewport captures show the layout; reflow measurements used a 1000 px height.

## Next increment

Monthly category budgets (2D.1) are implemented. [Cash-flow trends (2D.2)](budgets-prototype-plan.md#step-2d2-cash-flow-trends) remain planned and require reconciled historical fixtures before multi-month charts. Recurring-expense review follows in 2D.3, then import/connection walkthroughs in Step 2E. Production data and security foundations remain separate work.
