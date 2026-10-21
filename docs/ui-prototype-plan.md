# UI prototype plan

The prototype establishes visual design and everyday interactions before connecting financial accounts. Steps 2A, 2B.1, and 2B.2 provide the Overview, frontend foundation, investment holdings list, and holding details and are merged into `main`. Banking activity/inspection, transfer matching, and category corrections through Step 2C.3 are also merged into `main`. The [implementation notes](ui-prototype.md) describe these screens and their verification. [Step 2D.1](budgets-prototype-plan.md#step-2d1-monthly-category-budgets) adds monthly category budgets; Step 2D.2 adds reconciled cash-flow trends; Step 2D.3 adds recurring-expense review. Step 2D is merged into `main`. [Step 2E.1](imports-prototype-plan.md#step-2e1-connections-and-source-coverage) adds source coverage and connection-status walkthroughs. Step 2E.2 adds read-only bank samples, previews, and row inspection. Step 2E.3 adds reversible bank review decisions and sample-only receipts. Investment samples in 2E.4 remain planned.

## Scope and visual direction

The Overview answers three questions: what assets are tracked, where they are held, and which data needs attention. React, TypeScript, and Vite provide a reusable frontend foundation with a small, pinned dependency set.

Use the Indigo & Apricot palette: pale indigo backgrounds and warm apricot highlights in light mode, deeper indigo surfaces and bright apricot accents in dark mode. Keep readable type, tabular numbers, thin separators, and limited elevation. Allocation charts use four distinct hues, contrasting separators, and matching labeled legends. Follow the system theme initially and offer an explicit control. Bundle fonts and icons locally. Accompany meaningful color with text or icons.

Desktop uses a narrow sidebar; mobile uses a compact header and navigation drawer. Keep a neutral working title. Favor useful charts and compact account rows, respect reduced motion, and preserve keyboard access.

The prototype runs on loopback with fabricated fixtures. Backend services, databases, authentication, real statements, provider connections, live quotes, trading, and deployment are outside its scope. Keep a visible sample-data label on every screen size.

## Increments

| Increment | Deliverable | Status |
| --- | --- | --- |
| 2A | Frontend foundation, responsive shell, Overview | Merged into main |
| 2B.1 | [Investment holdings list](#holdings-list-2b1) | Merged into main |
| 2B.2 | [Holding detail views](#holding-details-2b2) | Merged into main |
| 2C.1 | [Bank activity and transaction inspection](banking-prototype-plan.md#step-2c1-bank-activity) | Merged into main |
| 2C.2 | [Transfer matching review](banking-prototype-plan.md#step-2c2-transfer-matching-review) | Merged into main |
| 2C.3 | [Category review and corrections](banking-prototype-plan.md#step-2c3-category-review) | Merged into main |
| 2D.1 | [Monthly category budgets](budgets-prototype-plan.md#step-2d1-monthly-category-budgets) | Merged into main |
| 2D.2 | [Cash-flow trends](budgets-prototype-plan.md#step-2d2-cash-flow-trends) | Merged into main |
| 2D.3 | [Recurring commitments](budgets-prototype-plan.md#step-2d3-recurring-commitments) | Merged into main |
| 2E.1 | [Connections and source coverage](imports-prototype-plan.md#step-2e1-connections-and-source-coverage) | Implemented |
| 2E.2 | [Bank import previews](imports-prototype-plan.md#step-2e2-bank-import-previews) | Implemented |
| 2E.3 | [Review decisions and completion](imports-prototype-plan.md#step-2e3-review-decisions-and-completion) | Implemented |
| 2E.4 | [Investment statement walkthroughs](imports-prototype-plan.md#step-2e4-investment-statement-walkthroughs) | Planned |

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

Currency conversion uses a labeled, dated fictional rate. Apply the selected currency to primary monetary displays across every implemented screen; retain labeled original amounts and document minor-unit arithmetic and rounding. Historical conversions are display equivalents, not historical FX or tax basis. Changing a chart range does not alter the current summary.

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

## Step 2B: Investments

Status: the holdings list (2B.1) and holding details (2B.2) are merged into `main`.

Help answer what is owned, where it is held, how much it is currently worth, and whether its units and prices are current. Retain Indigo & Apricot, the shared navigation/header, theme and currency controls, amount masking, and visible sample-data labeling. The prototype continues to use bundled fictional records only.

### Delivery increments

| Increment | Deliverable | Status | Conventional commit |
| --- | --- | --- | --- |
| 2B.1 | Individual holding fixtures, Overview reconciliation, Investments navigation, searchable/filterable/sortable holdings list | Merged into main | `feat(investments): add searchable holdings overview` |
| 2B.2 | Holding detail pages, source dates, sample activity, and UBS ESPP lot presentation | Merged into main | `feat(investments): add holding detail views` |

Each increment includes its relevant tests, documentation, and light/dark desktop/mobile screenshots. Follow the existing `dev` to `main` PR workflow. Holding names now link to their account-specific detail pages.

### Holdings list: 2B.1

Implemented with 14 holdings across four investment accounts. Source-date sorting uses the holdings snapshot date; quote/NAV dates are displayed independently. Search, filters, sorting, expanded filters, and scroll survive navigation for the current session. Step 2B.2 adds links and return focus to the originating holding.

Use a full-width working area with a compact summary, search/filter toolbar, and holdings table. Mobile uses readable cards with the same information hierarchy rather than a compressed desktop table.

| Area | Planned behavior |
| --- | --- |
| Summary | Investment value, holding count, investment-account count, and missing/stale coverage. Bank and broker cash remain in Overview and are excluded from this list. |
| Search | Case-insensitive literal search across instrument name, ticker, and fund name; trim surrounding whitespace. Do not interpret input as a regular expression. |
| Filters | Instrument type (stock, ETF, mutual fund), market (India/US), account, native currency, direct/regular fund plan, and data status. Filters combine; active filters and a clear-all action stay visible. |
| Market meaning | Use explicit instrument market metadata; do not infer market from currency or represent an ETF's listing market as its underlying geographic exposure. |
| Desktop columns | Instrument and plan/type, account, units, price/NAV and value in the selected reporting currency with labeled original quotes, portfolio weight, and freshness. |
| Mobile cards | Name/plan, account, reporting value, weight, and freshness first; units and reporting/original price/NAV remain available without horizontal page scrolling. |
| Sorting | Value descending initially; name, value, weight, and source-date sorting with explicit direction. Sort numbers and timestamps, not formatted strings. Unknown values remain last in either direction; ties use a stable identifier. |
| Filter results | Show matching count and matching valued subtotal separately from the overall investment summary. Preserve filters when changing currency/theme or visiting details. |
| Portfolio weight | Percentage of all currently valued investment holdings, excluding cash. Filtering never changes the denominator. Unknown holdings show an unavailable weight; partial coverage is labeled. |
| No matches | Explain that filters returned no matches and offer clear-all; distinguish this from an account with no holdings. |

Rows represent one instrument in one account and, for mutual funds, one sample folio where relevant. Keep separate account/folio rows for the same instrument rather than merging them by name or ticker. Distinguish direct versus regular plans and growth versus distribution options. UBS Accenture shares carry an ESPP label, without implying a different security from the same shares held elsewhere.

Use approximately 12–16 fictional holdings across INDmoney India, INDmoney US, advisor funds, and UBS. Include Indian/US stocks and ETFs, fractional units, direct and regular funds, the same security in two accounts, a missing NAV, and stale holdings with a separately dated price. Keep HDFC/SBI and broker cash in the shared Overview data.

### Holding details: 2B.2

Implemented for every known holding, including direct routes with opaque IDs. Unknown identifiers have an unavailable view. Selected activity is supplied only where fixtures contain it; absent records are explained. The three UBS lots total 24 units, retain USD purchase amounts, and distinguish a zero fee from an unknown fee. See [implementation and verification](ui-prototype.md#holding-details).

Selecting a holding opens a dedicated detail page. A two-column desktop layout places the current position and source information beside supporting records; mobile stacks those sections. A breadcrumb and Back to holdings action restore the list's filters, sorting, and scroll position. Browser Back/Forward and direct navigation work, with a clear unavailable view for unknown holding identifiers.

| Section | Planned content |
| --- | --- |
| Identity | Name, ticker or sample scheme identifier, instrument type, market, native currency, account, and applicable fund plan/option. |
| Position | Units, reporting price/NAV with labeled original quote, native value, reporting-currency value, investment weight, and explicit missing-value labels. |
| Source and freshness | Separate holdings date, price/NAV date, and dated fictional FX rate. Explain stale or incomplete coverage beside the affected fields. |
| Fund information | Direct/regular and growth/distribution distinctions, friendly sample folio label, units, and NAV date. |
| Sample activity | A small dated list of relevant purchases/dividends/fees with reporting-currency display, labeled original amounts, and clear event labels. Mark it as selected sample activity rather than a complete ledger. |
| UBS ESPP lots | Illustrative purchase dates, remaining units, purchase price, and fees when supplied. Open-lot units reconcile to the sample holding; acquisition details are not presented as a tax-basis calculation. |

Display source-supplied acquisition amounts only when the fixture contains them. Unknown cost or tax basis stays unknown. Do not derive purchase cost from today's market value or turn current FX into historical acquisition FX. P&L, daily gains, realized returns, XIRR/TWR, tax calculations, forecasts, and per-holding performance charts remain outside this increment.

### Shared data and arithmetic

Replace category-only investment fixtures with individual records and derive both screens from that shared collection. Do not maintain independent Overview and Investments totals. Keep instrument identity, account/folio identity, holding snapshot, quote/NAV, and optional activity/lot records distinct; ticker alone is not a holding identifier.

Preserve the existing baseline: full investment value **INR 47,96,290**, cash **INR 2,89,790**, and tracked assets **INR 50,86,080**. The partial fixture continues to exclude the advisor holding worth INR 4,25,000 in the complete fixture, giving known investments of **INR 43,71,290** and tracked assets of **INR 46,61,080**. Unknown values are not zero. Account totals and class allocations reconcile to the same underlying positions.

Represent fractional units and native prices/NAVs with exact scaled integers, with explicit fixture scales of up to eight decimal places for units and six for quotes. Multiply exactly, then round native valuation to currency minor units using the existing half-away-from-zero rule before applying the dated demo FX conversion. Keep accounting arithmetic separate from chart coordinates and displayed percentages. Test the rounding boundaries; do not use binary floating point to derive financial totals.

INR remains the canonical aggregate currency for this prototype. Changing the display currency does not change holdings, source quotes, or canonical totals; it changes their display equivalents. Explain any minor-unit display reconciliation difference caused by converting independently rounded rows. No production import, valuation, or cost-basis engine is introduced.

### States, privacy, and navigation

- Exercise populated, loading, empty, missing-price, stale-holdings, and failed-load states, plus no search matches and an unknown detail identifier. A failure retains the last usable fixture view and its coverage labels.
- Extend Hide amounts to quantities, prices/NAVs, acquisition amounts, lot records, and activity amounts, including accessible labels and hidden content. Instrument/account names and portfolio percentages remain visible, consistent with Overview. Masking remains visual privacy; bundled fixture data can be inspected.
- Enable Overview and Investments navigation; other destinations retain their planned status. Reuse the shared theme, currency, and privacy state across routes.
- Use a minimal client-side route layer with allowlisted screen names and opaque fixture identifiers. Refresh and Back/Forward must work on the local preview. Search text, financial values, and account/folio details must not be embedded in URLs.
- Keep search, filters, sorting, and list scroll state in memory. Reload returns these controls to defaults; only the existing display preferences persist. Avoid new routing/table dependencies unless a concrete need emerges.
- Use semantic table headers and sorting controls, labeled filters, visible focus, keyboard-operable holding links, and polite result-count announcements. Move focus to the detail heading on entry and restore it to the originating row, or the list heading when that row is unavailable, on return.

### Security boundary

No real statements, identifiers, broker credentials, account connections, uploads/downloads, analytics, remote fonts/logos, or external runtime requests. Continue loopback-only servers and the existing content policy. Render names, searches, and other strings as text; validate routes against known fixtures. Do not store financial records or searches in local/session storage, URLs, logs, or telemetry.

Backend services, authentication, PostgreSQL/Supabase, hosted deployment, automated imports, live prices, trading buttons, buy/sell flows, watchlists, and recommendations remain separate work. The screen must not imply these capabilities exist.

### Verification targets

| Area | Required evidence |
| --- | --- |
| Financial consistency | Individual holdings reconcile to Overview, accounts, and classes in full/partial states; fractional valuation and FX rounding have known-result tests; duplicate securities across accounts stay separate; cash is excluded from Investments. |
| Search/filter/sort | Combined filters, whitespace/case handling, no matches, clear-all, numeric ordering in both currencies, stable ties, unknown values last, and unchanged weight denominator. |
| Details and navigation | Correct row opens correct account/folio detail; direct links and unknown identifiers; Back/Forward; restored filters, sorting, focus, and scroll. |
| Privacy and safe rendering | Masking covers new values in visible/hidden DOM and accessible text across routes; markup-like names/searches remain plain text; URLs/storage do not receive financial values or search terms. |
| States | Missing prices, separate stale holdings/price dates, retained data on failure, retry, empty holdings, and empty search results remain distinguishable. |
| Visual/accessibility | Both themes at 1440, 768, and 390 px; 320 px reflow; long names and large amounts; keyboard flows, contrast, named controls, and chart/list alternatives. Revisit outstanding enlarged-text, 400% zoom, reduced-motion, and screen-reader checks and record actual limitations. |
| Engineering | Existing Overview regressions plus targeted new tests, TypeScript checks, production build, dependency review if dependencies change, local security-header/network checks, and screenshots with fictional data. |

Update the README and prototype implementation notes as each increment becomes available. Mark each increment implemented only when its behavior exists and its evidence is recorded.

## Step 2C: Banking

The [banking prototype plan](banking-prototype-plan.md) defines three increments: searchable HDFC/SBI activity with transaction inspection, explainable transfer matching with reversible decisions, and category review with individual/bulk corrections. It specifies shared balance reconciliation, original-currency arithmetic, incomplete coverage, privacy, and acceptance evidence. Activity and inspection (2C.1), transfer matching review (2C.2), and category review (2C.3) are implemented. Step 2D retains budgets and cash-flow trends.

## Step 2D: Budgets and cash flow

The [budgets and cash-flow plan](budgets-prototype-plan.md) defines monthly category limits and actuals (2D.1), reconciled historical cash-flow trends (2D.2), and recurring-expense review (2D.3). It keeps planned amounts separate from recorded activity, preserves transfer/refund rules, and distinguishes source coverage from classification coverage. October remains month-to-date; prior months require reconciled source fixtures. Monthly category budgets (2D.1) are implemented with in-memory limits and separate undo/reset. Cash-flow trends (2D.2) are implemented with reconciled August/September statements, explicit coverage, matching-day comparisons, daily details, and full source inspection. Recurring review (2D.3) is implemented with supplied monthly evidence, reversible decisions, missing-source handling, and fixed/range commitments kept separate from actuals. All inherit the existing security/privacy boundary.

## Step 2E: Import review and connection status

The [Step 2E plan](imports-prototype-plan.md) separates source coverage/status walkthroughs, read-only bank batch previews, reversible review decisions with sample receipts, and investment statement scenarios. Connections now provides source inspection and local status/recovery simulations. Sample imports provides seven HDFC/SBI examples with source arithmetic, issue counts, and original/normalized row inspection. Step 2E.3 provides evidence-bound choices, undo/reset, set-aside/reopen, and sample-only receipts with separate source and combined-record reconciliation. All examples remain bundled and local: no uploads, provider sign-in, real parser, network sync, or committed financial changes. Sample completion records only an in-memory review receipt. Existing financial baselines and review domains remain unchanged.
