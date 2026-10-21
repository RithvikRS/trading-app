# Budgets and cash-flow prototype plan

Status: monthly category budgets (2D.1) are implemented. Cash-flow trends (2D.2) are implemented; recurring commitments (2D.3) remain planned. Banking activity, transfer matching, and category corrections through Step 2C.3 are merged into `main`. See the [implementation notes](ui-prototype.md#monthly-category-budgets) and [banking contract](banking-prototype-plan.md).

The Budgets workspace should answer three questions: how classified spending compares with monthly limits, how income and spending change over time, and which recurring expenses are expected next. Security, traceable calculations, and honest coverage take priority over automation. Continue using fictional HDFC/SBI records, the Indigo & Apricot themes, and the shared currency/privacy controls.

## Delivery increments

| Increment | Deliverable | Status | Conventional commit |
| --- | --- | --- | --- |
| 2D.1 | Monthly category budgets, reversible limit editing, actual-spending breakdowns, and source inspection | Implemented | `feat(budgets): add monthly category budgets` |
| 2D.2 | Reconciled historical fixtures, cash-flow trends, comparable-period analysis, and coverage breakdowns | Implemented | `feat(budgets): add cash-flow trends` |
| 2D.3 | Explainable recurring-expense suggestions, review decisions, and expected commitments | Planned | `feat(budgets): add recurring expense review` |

Each increment includes its calculations, meaningful tests, documentation, and light/dark desktop/mobile evidence in a focused `dev` to `main` PR. Later views retain a planned label until their behavior exists. Step 2E remains the import/connection walkthrough.

## Workspace and interaction design

Enable a top-level `#/budgets` destination with Monthly budgets, Cash flow, and Recurring views as their increments arrive. Default to October 2026 and visibly distinguish the calendar month from available activity through 20 October, 10:00 IST. Use this fixed sample cutoff, not the computer's current date, for period and expected-payment labels.

| Area | Design |
| --- | --- |
| Header | Month/view selection, sample-data label, and visible coverage; reuse global INR/USD, masking, and theme controls. |
| Monthly summary | Planned category limits, classified spending within those categories, and remaining/over-limit amount; unbudgeted spending and unresolved coverage appear separately. |
| Category rows | Category, monthly limit or Not set, net classified spending, remaining/over-limit amount, text status, and a restrained progress bar. Sort over-limit categories first, then use stable category order. |
| Detail | Expand a category into gross expenses, verified refunds, net spending, source counts, and contributing transactions. Open the existing source inspector and return to the same month/category, scroll position, and trigger. |
| Cash flow | Compact income/spending summaries, a readable grouped chart, an equivalent data table, and a separate bank-movement reconciliation. Distinguish full months from month-to-date. |
| Recurring | Expected expenses ordered by date, with amount/evidence/status and source links. Keep suggestions and reviewed commitments distinct. |

Use semantic rows on desktop and stacked cards on mobile. Prefer one primary action per section, explicit labels, tabular numbers, and visible keyboard focus. Budget editing uses a small accessible dialog with Save/Cancel, field-level errors, focus containment, Escape, and return focus. Saving a limit changes only local planning data. Announcements contain counts/status, not amounts. Charts must have keyboard-accessible selection and a table; no hover-only information or color-only distinctions.

Selections, expanded categories, filters, and scroll remain in memory across navigation. Direct reload of Budgets uses default controls. Transaction inspection uses allowlisted opaque record IDs; a session-only origin restores the Budgets context on close or Back. Direct reload of a transaction route continues to work as ordinary Banking inspection. Do not place budget amounts, payees, search text, or review decisions in URLs.

## Step 2D.1: Monthly category budgets

Implemented for October with eight supplied limits across ten expense categories, individual limit editing/removal, separate budget undo/reset, source-linked actuals, coverage messaging, and shared privacy/currency controls. Historical months are available in Cash flow; recurring review remains planned. The rules below define this increment's behavior; [implementation evidence](ui-prototype.md#monthly-category-budgets) records its actual checks and limits.

Start with October's existing 28 bank records and a small set of supplied monthly limits. Include under-limit, exactly-at-limit, over-limit, explicit-zero, and unset categories in the fixtures. Every actual comes from current effective classifications and verified refund evidence, never a separately maintained dashboard total.

Budgets belong to the sample owner and cover both tracked banks together. Use one limit per owner, calendar month, and expense category. Do not introduce overlapping account budgets or an independent overall limit. Cash-flow account filters in 2D.2 do not redefine this all-account budget scope. Use the existing expense taxonomy; income, internal transfers, investment funding, refunds, and unresolved activity are not editable budget categories.

Allow adding, editing, and removing a category limit. Removal restores Not set; zero means an explicit zero-spend target. Cancel makes no change; saving an unchanged value creates no history entry. Provide Undo budget change and Reset sample budgets with a clearly separate history from Banking's transaction-review history. Budget reset does not reset classifications, and Banking reset does not reset limits. Reload resets both local domains to their supplied fixtures.

Limits are canonical INR minor units. The editor explicitly says INR even when reporting in USD, with a labeled display equivalent; changing reporting currency must never reinterpret the input. Accept a trimmed decimal string from 0 to 999999999.99, at most two fractional digits; reject empty input on Save, negative values, separators, exponent notation, non-finite values, and excess precision. Bound input length before parsing. Preserve the entered value and explain errors without rounding it silently. Removing a limit is a separate action. Limit editing is confined to October. Historical month selection in 2D.2 applies to Cash flow; historical budget limits are not invented or copied.

| Calculation | Contract |
| --- | --- |
| Category actual | Posted expense debits in the category minus verified refund credits attributed to it, within the selected booking month and available cutoff. |
| Planned total | Sum of set category limits, including explicit zero limits. If none are set, show No budgets set instead of a misleading zero-budget result. |
| Budgeted actual | Sum of net actuals only for categories with a set limit. Show unbudgeted category actuals separately. |
| Remaining | Limit minus net category actual; a negative result is Over limit. The month-to-date actual is compared with the full-month limit, without proration or annualization. |
| Progress | Actual divided by a positive limit for presentation only; cap the visual bar at 100% while retaining the true over-limit amount and percentage. Zero/unset limits have no percentage. |
| Negative actual | Preserve refund-driven negative spending. Show Net refund; remaining can exceed the original limit. Use an empty progress bar and an explanation instead of a negative or misleading fill. |
| Missing coverage | Show actuals as available classified activity. Suppress definitive Under limit/remaining-to-spend claims where missing records or unresolved outgoing activity could change the result. Any positive difference is labeled Provisional remaining, never available cash. An observed over-limit amount remains provisional because missing credits could offset it. |

The source ledger may be complete through the cutoff while classification remains incomplete. Show both facts independently, including unresolved outgoing/incoming totals and pending counts. A category with no records is known zero only when the relevant source period is complete and unresolved activity cannot affect it; otherwise label the observed zero as incomplete. Link unresolved coverage to Banking's review view without changing its classifications automatically.

Category corrections, transfer decisions, undo, and resets must update budget actuals immediately through the shared review model. A purchase correction moves its verified refund attribution too. A refund is counted in its own booking month, even when its purchase lies outside that month; it does not rewrite prior-month spending. General refund matching remains outside scope.

No rollover, automatic budget copying, household/shared budgets, goals, envelopes, prorated limits, predicted overspending, or safe-to-spend calculation is included.

## Step 2D.2: Cash-flow trends

Implemented with one 58-record ledger, six independently supplied statement balances, explicit account/day coverage, three selectable months, daily charts/tables, category-filtered source inspection, and exact reconciliation. See [fixture totals and implementation evidence](ui-prototype.md#cash-flow-trends). The rules below define this increment’s contract.

Add fictional August and September 2026 source records and per-account period coverage so three months of trends have actual ledger evidence. October remains month-to-date through the existing cutoff. Reconcile each complete historical account period from opening through posted movements to closing, and reconcile September closing to October opening. Preserve October's current record identities, source fields, 28-record default view, account snapshots, and Overview asset baseline.

Keep one authoritative record collection with explicit period-aware selectors. Historical records must also be inspectable/filterable in Banking and participate in the same classification model; do not create a second, inconsistent analytics ledger. Scope statement reconciliation to its own period so adding history cannot inflate October's calculated balance. Explicitly model per-account coverage intervals and gaps, rather than inferring completeness from the earliest/latest observed transaction. Document any added fixture evidence, known-result totals, and reconciliation before enabling history.

Allow All accounts, HDFC, or SBI for cash flow only. Start with the three supplied months and daily detail within the selected month, with table equivalents. Do not offer longer ranges until source history exists. A day without transactions is zero only inside known-complete coverage; absent history and days after the current cutoff are gaps, not zeros. Compare a current month-to-date window with the same first N calendar days of the prior month, using the smaller supported day count where needed. Show an absolute/percentage comparison only when both windows have equivalent account coverage and complete relevant classification. A zero prior value has no percentage change. Otherwise explain why comparison is unavailable; never compare 20 days against an unlabeled full month.

Use the following terms consistently:

| Metric | Meaning |
| --- | --- |
| Classified income | Posted credits effectively categorized as salary, interest, or other income. Excludes refunds, transfers, investment movements, and unresolved credits. |
| Gross expenses | Posted debits with an eligible expense category, including separate bank fees. |
| Verified refunds | Eligible credits with valid purchase evidence, attributed once to the purchase category in the refund's booking period. |
| Net classified spending | Gross expenses minus verified refunds; may be negative. |
| Classified surplus/deficit | Classified income minus net classified spending. Label it as classified activity, not savings, disposable income, account balance, or investment return. |
| Net bank movement | All posted bank credits minus all posted bank debits in scope, including transfers and investment funding. Pending entries never contribute. |
| Coverage breakdown | Separate investment inflows/outflows, confirmed transfer credits/debits, unresolved credits/debits, and pending counts/amounts. These explain why classified surplus differs from bank movement. |

For the same account/date scope, require the exact identity:

```text
net bank movement = classified income - net classified spending
                  + investment credits - investment debits
                  + confirmed transfer credits - confirmed transfer debits
                  + unresolved credits - unresolved debits
```

Every posted entry appears in exactly one role, with verified refunds included in net spending. This identity reconciles available records; it does not establish completeness. An account or monthly boundary can include only one transfer leg: keep that signed movement in the bridge and exclude it from income/spending. Pair validity must use the full available evidence, not only the chart's filtered window. Never assume transfer totals cancel in every scope. Missing counterpart evidence makes the retained pair unresolved under the existing rules.

| Current October baseline, before local changes | INR |
| --- | ---: |
| Classified income | 95,250.00 |
| Gross expenses | 36,764.90 |
| Verified refunds | 800.00 |
| Net classified spending | 35,964.90 |
| Classified surplus | 59,285.10 |
| Investment outflow | 15,000.00 |
| Confirmed transfer credits / debits | 25,000.00 / 25,000.00 |
| Unresolved credits / debits | 18,000.00 / 16,500.00 |
| Net bank movement | 45,785.10 |

Initial posted bank credits/debits are INR 1,39,050 / 93,264.90. Opening balances total INR 2,15,484.90; closing balances total INR 2,61,270.00. Keep broker cash and investment trades outside this bank-only reconciliation. Partial mode retains the supplied bank balances and exposes the missing SBI bill; no artificial adjustment may make the ledger balance.

Use distinct, high-contrast income and spending series with a visible zero baseline, negative-spending support, dates, and a legend. The adjacent table exposes all figures and coverage without inspecting a chart. Clicking a month/day/category reveals contributing source records while preserving the overall scope summary. Classification changes update charts, tables, budget actuals, and coverage together. Do not add forecasts, savings rates, investment-return calculations, live FX, or a projected bank balance.

## Step 2D.3: Recurring commitments

Use a small set of supplied monthly expense patterns supported by the historical fixtures: fixed rent/subscription, a variable utility bill, an ambiguous payment, and a missing-source example. Each suggestion identifies the same known owner/account, stable fictional payee, expense role, interval, observed dates/amounts, and supporting source IDs. At least two distinct monthly occurrences support a suggestion; repeated same-day café payments do not establish recurrence. Evidence suggests a pattern, not a contractual obligation. No external enrichment or learned model is introduced.

Allow Confirm recurring, Dismiss suggestion, Restore suggestion, and Undo recurring change. Keep these decisions in their own local history with Reset sample recurring decisions. Revalidate source identity, eligibility, and non-overlapping occurrence membership before applying; stale evidence cannot silently confirm a pattern. A source record cannot satisfy two occurrences. Transfer, investment, refund, pending, and unresolved records cannot establish a posted expense occurrence. If later category/transfer review or missing source evidence invalidates a reviewed pattern, retain the decision but mark Needs review and exclude it from expected totals until evidence is valid again.

For reviewed, valid patterns, show the supplied monthly due date and fixed expected amount or observed range. Variable ranges remain ranges; do not manufacture a precise estimate or sum them as fixed commitments. Monthly dates such as the 31st clamp to that month's last day and retain their original recurrence day for the next month. This release does not infer weekly/annual schedules or business-day adjustments.

Separate Recorded, Pending source, Expected, and Not observed in available records. Pending is not paid. A missing occurrence with incomplete coverage stays Unknown; avoid claiming overdue or unpaid. Link each recorded occurrence to its actual source. Expected commitments cover the remainder of the selected month after the sample cutoff and are shown separately from historical actuals; historical months show evidence only. Review decisions never create a payment or transaction. Deduct nothing from bank snapshots, actual spending, budget remaining, or cash-flow totals for an expected payment. Include recorded expenses exactly once through the ledger, not again through the schedule.

No payment initiation, reminders, notifications, background scheduling, automatic cancellations, contract management, or arbitrary recurring-rule editor is included.

## Shared financial, security, and state rules

- Reuse effective classifications, transfer membership, refund validation, and exact money helpers. Keep source records immutable. Store limits as INR `bigint` paise and aggregate before presentation; floating point is for chart geometry/ratios only. Same-period category totals must reconcile to the existing classified-spending preview.
- All primary monetary displays follow global INR/USD, including budget limits, remaining amounts, chart axes/tooltips/tables, historical totals, coverage, and recurring amounts. Label original/source or edit-currency amounts explicitly. Use the existing dated fictional FX rate for display only; never claim historical FX or compound rounding by converting a prior display value.
- Hide amounts removes limits, input values, actuals, remaining amounts, recurring ranges, axes, tooltips, data tables, accessible values, and announcements from the rendered DOM. Hide budget progress and financial chart geometry while masked; keep neutral placeholders and nonfinancial labels. If an editor is open, retain its draft only in memory, replace the monetary input, and disable Save until amounts are shown. Masking remains visual privacy, not access control.
- Use loopback-only servers, bundled assets, existing restrictive browser headers, fixed taxonomy, allowlisted records/months, bounded inputs, and plain-text rendering. No real data, file input/export, provider access, credentials, analytics, external requests, database, backend, trading, or deployment work.
- Budget drafts/limits, recurrence decisions, all histories, chart selections, filters, and searches stay in memory. Only existing display preferences persist. Do not serialize financial values or state into URLs, browser storage, logs, or telemetry. Future production requires authenticated ownership checks and durable audited recovery; client fixture checks do not provide those protections.
- Populated/partial/loading/error states preserve compatible local decisions; loading hides totals and clears action previews. Failure retains the last usable source snapshot and decisions with its dates and warnings; retry must not duplicate records or decisions. Empty clears local review/planning state and selections, and restoring sample data reinstates supplied fixtures. Each domain's explicit Reset affects only its own decisions, not source records or other domains. Reload returns all domains to initial fixtures and retains only display preferences.
- Distinguish no budgets, no classified activity, zero spend, no matching rows, unsupported month, missing history, incomplete source coverage, unresolved classification, and failed loading. Never render an unavailable monetary total as zero or extrapolate beyond the sample cutoff.

## Acceptance evidence

| Area | Required evidence |
| --- | --- |
| Budget integrity | Exact limit parsing; zero/unset/invalid values; edit/cancel/remove/undo/reset; net-refund and over-limit cases; budgeted plus unbudgeted actuals reconcile; no proration; source balances unchanged. |
| Classification | Corrections and undo propagate across Banking, Budgets, trends, and the Overview excerpt; transfers/investments/pending excluded from consumption; linked refunds follow purchase categories and their own booking month; incomplete evidence stays unresolved. |
| Historical accounting | Prior months reconcile per account and join October opening balances; October default records/snapshots and asset totals unchanged; no cross-period double counting; same-day repeated records remain distinct. |
| Cash-flow math | Known-result bridge above; account and month boundaries with one transfer leg; zero/negative periods; incomplete coverage versus known zero; comparable-day windows; no division by zero or misleading growth claim. |
| Recurrence | Explainable evidence; explicit decisions; no duplicate occurrences; changed/missing evidence; variable ranges; month-end/leap-year dates; pending versus recorded; expected values excluded from all actuals. |
| Privacy/security | No masked-value leaks in DOM, forms, chart geometry, accessible text, live messages, URLs, logs, or storage; bounded parsing; markup-like labels stay text; local assets and browser policy checks. |
| Navigation/states | Direct/invalid routes, month/view state, source inspection and origin return, Back/Forward, keyboard dialog containment, focus fallback, loading/empty/partial/error/retry, and each reset/reload boundary. |
| Visual/accessibility | Indigo & Apricot in both themes at 1440, 768, and 390 px; 320 px reflow, long labels/large values, keyboard-operable charts with tables, contrast, focus, and primary touch targets. Revisit enlarged text/400% zoom, runtime reduced motion, and screen-reader checks; record any limits honestly. |
| Engineering | Relevant data/component tests and existing workspace regressions, TypeScript, production build, dependency/license review if changed, and fictional screenshots. A planning-only change requires document/link checks, not unrelated runtime tests. |

Record actual implementation and evidence in [prototype notes](ui-prototype.md) as each increment is delivered. These requirements do not claim that the planned UI, calculations, or production security controls already exist.
