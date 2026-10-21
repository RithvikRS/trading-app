# Banking prototype plan

Status: bank activity and transaction inspection (2C.1) are implemented. Transfer matching review (2C.2) and category corrections (2C.3) remain planned. The investment screens through Step 2B.2 are merged into `main`. See the [implementation notes](ui-prototype.md#banking-activity-and-inspection) for delivered behavior and evidence.

The screen should make three things clear: what moved, whether a movement belongs to another tracked account, and which classifications need attention. Security and financial integrity take priority over automation. All records and review actions use fictional data in memory.

## Delivery increments

| Increment | Deliverable | Status | Conventional commit |
| --- | --- | --- | --- |
| 2C.1 | Bank activity, dated balances, filters, and transaction inspection | Implemented | `feat(banking): add searchable bank activity` |
| 2C.2 | Explainable transfer candidates, pair review, and reversible matching | Planned | `feat(banking): add transfer matching review` |
| 2C.3 | Category suggestions, individual/bulk corrections, and undo | Planned | `feat(banking): add transaction category review` |

Each increment delivers working behavior, meaningful tests, documentation, and light/dark desktop/mobile evidence through the existing `dev` to `main` workflow. Transfer and category editing become interactive only in their respective increments. Budgets, recurring detection, monthly cash-flow charts, and category trends belong to Step 2D. Import walkthroughs belong to Step 2E.

## Shared visual direction

Retain Indigo & Apricot, the shared header/sidebar, currency and privacy controls, and a visible sample-data label. Use a full-width Banking workspace with compact HDFC/SBI account cards above the activity area. Dates, amounts, account names, and review status should be easy to scan; use text and icons alongside color.

Desktop uses a semantic transaction table and a right-side inspection panel. On mobile, transactions become readable cards and inspection uses a full-height dialog. Keep primary actions reachable without horizontal scrolling, with at least 44 px primary touch targets where practical. Avoid a chart in this increment: activity and outstanding reviews are the main tasks.

The activity toolbar contains search, date range, account selection, and an expandable filter area. Later increments add Transfers and Categories review views inside Banking, each with its own outstanding-item count. The separate top-level Activity destination remains planned; this increment covers bank records only.

## Step 2C.1: Bank activity

Implemented with 28 fictional transactions, of which 26 are posted and two pending. Inspection uses a modal panel on the right on desktop and fills the viewport width on mobile. Source disclosures reconcile the entire supplied statement period independently of list filters. Initial pair/category evidence remains read-only; there is no candidate-matching engine or category editor yet.

| Area | Planned behavior |
| --- | --- |
| Account cards | HDFC and SBI booked balance snapshots, source dates, currency, and coverage. Selecting a card filters activity; an All accounts choice clears that selection. Label balances as booked snapshots, without implying available funds. |
| Activity summary | Credits, debits, and count for the selected accounts/date range, with pending items counted separately. Label credits/debits as money in/out including transfers, not income/spending. Balance cards do not change with date, search, or category filters. |
| Search | Literal, case-insensitive matching of description, counterparty label, and friendly sample reference. Trim surrounding whitespace; never interpret a regular expression or markup. |
| Filters | Account, inclusive booking-date range, debit/credit direction, posted/pending status, recorded category, and review status. Combine filters, show active chips, and provide clear-all. Default to all accounts and the full supplied period. |
| Results | Distinguish account/date-range summaries from the filtered result count and posted debit/credit subtotals. Search and classification filters must not silently redefine the account/date-range summaries. |
| Rows/cards | Booking date, description/counterparty, account, debit or credit in the selected reporting currency with labeled original INR, category, and review/status label. Sorting supports date, amount, and description in both directions; amount compares absolute minor units, with direction shown separately and stable IDs breaking ties. |
| Inspection | Original narration, friendly reference, posted/pending state, booking date, optional value date, reporting and original amount/direction, source period, and provenance. Separate source fields from derived classifications and review decisions. |
| Coverage | Explain stale snapshots, missing activity, unknown balances, and pending records individually. Do not infer that a fresh balance establishes complete transaction coverage. |

Use `#/banking` and `#/banking/<transaction-id>` with allowlisted opaque fixture IDs. A direct transaction route opens the Banking screen with its inspector; reload retains the destination but resets temporary controls. Unknown or malformed identifiers use an unavailable view without echoing raw URL content.

Retain filters, search, sort, review view, scroll, and temporary review state while navigating within the app. Opening inspection focuses its heading; closing returns focus to the originating row, or the list heading if the row is no longer present. Browser Back/Forward must work. Mobile dialogs contain focus, support Escape, and restore it on dismissal. Announce result-count changes politely without including financial amounts.

### Fixture and reconciliation contract

Use approximately 24–30 transactions across the two INR savings accounts, with a complete posted sample period of 1–20 October 2026 up to the existing snapshot cutoff. Include salary, interest, groceries, bills, fees, investment funding, a verified refund, repeated legitimate same-amount payments, a confirmed transfer, unique and ambiguous candidates, an unmatched leg, and separate pending examples. Do not fabricate execution times for date-only records.

Every transaction has a stable ID, account ID, source ID, booking date, optional value date, direction, positive minor-unit amount, status, original narration, and optional structured reference/category evidence. Keep source records immutable; classifications, match decisions, and review history are separate objects keyed by IDs. Similar text, amount, or date never establishes duplicate identity.

| Shared snapshot | INR |
| --- | ---: |
| HDFC booked balance | 1,86,420.00 |
| SBI booked balance | 74,850.00 |
| Bank balances combined | 2,61,270.00 |
| Broker cash, outside Banking | 28,520.00 |
| Overview bank and broker cash | 2,89,790.00 |

For each complete account period, the opening balance plus posted credits minus posted debits must equal the supplied closing balance. The complete fixture must preserve the existing Overview totals and history endpoint. Pending records do not enter this equation or posted summaries. Transaction classifications and transfer decisions never change signed ledger amounts or account balances.

Bank snapshots and transactions should share account/source identity with Overview. Overview must consume the same bank snapshot values, without adding the activity totals to them. Move its bank activity examples to the shared source records; do not keep an independently labeled matched transfer that can disagree with Banking review state. Investment activity remains separate. A selected Overview activity excerpt is not the entire bank ledger.

In partial mode, remove a known source row or period and mark coverage incomplete while retaining the independently supplied balance snapshot. Show the reconciliation difference as a review issue, never fill the gap with an invented transaction or opening-balance adjustment. Unknown balances stay unknown if such a fixture is supplied. Filtered or incomplete activity cannot establish a current balance; do not synthesize running balances from it.

Arithmetic uses the existing exact minor-unit helpers. Source transactions and reconciliation arithmetic remain in INR. The global currency preference controls primary bank balances, movement totals, matching subtotals, rows, reconciliation displays, and inspector amounts using the dated fictional rate. Differing original INR amounts remain labeled alongside the equivalents; raw narration stays verbatim. This conversion is for display and is not historical transaction FX; it cannot affect matching or classifications. Rounded display rows may differ from a converted aggregate by a minor unit.

## Step 2C.2: Transfer matching review

Provide a review queue with Suggested, Ambiguous, Unmatched, Confirmed, and Dismissed views. Show the two candidate entries side by side on desktop and stacked on mobile, including account, direction, amount, booking date, reference evidence, and why they were proposed. Describe evidence directly; do not invent confidence percentages.

### Candidate rules

- Only distinct posted transactions in different tracked accounts owned by the same sample owner are eligible. One must be a debit and the other a credit, with exactly equal native minor-unit amounts and the same currency.
- Use an explicit prototype window of at most three calendar days between booking dates. Calendar-date comparisons must not shift with browser timezone. This is a demo rule, not a statement of bank settlement guarantees.
- Equal amount/date only creates a suggestion. Matching structured source references may strengthen the explanation; arbitrary narration or similar merchant names cannot establish ownership or prove a transfer.
- Build candidates from all loaded eligible records, independently of activity filters. A hidden counterpart should be identified and inspectable without requiring the user to remove filters.
- If either entry has multiple eligible counterparts, show all competing candidates as ambiguous. Require selection and confirmation; never choose by list order or silently confirm even a unique candidate.
- Exclude already matched entries, same-account pairs, pending items, and fixtures explicitly known to be purchases, refunds, salary, or other non-transfer activity. Preserve unresolved cases for review.

### Review actions and invariants

Confirm pair links both source records atomically under one stable pair ID. A record can belong to only one confirmed pair; repeating an action is idempotent, and stale/conflicting choices fail visibly. The original debit and credit remain visible in account activity and balance reconciliation. Confirmed pairs appear once in the review summary, with both legs inspectable.

Dismiss candidate applies to that candidate pair, not to every possible counterpart or to the source transaction. Restore makes it eligible again. Unlink and Undo restore both records' previous classifications and review states, including an earlier manual category, without deleting source data. Confirm, dismiss, restore, unlink, and category changes share an in-memory change history; Undo reverses the latest applicable action atomically. These are local demo decisions, not changes at a bank or a production audit log.

Confirmed internal transfers are excluded from income/spending classification even when an account/date filter shows only one leg. A suggested or unmatched transfer remains unresolved and is not silently counted as spending or income. Show its amount separately as unreviewed coverage. Gross posted money-in/out totals still include every leg in the selected range.

Keep transfer fees as separate expense records; never stretch the amount comparison to absorb a fee. Unequal-amount, split/many-to-one, cross-currency, and cross-owner matching are outside this increment. Investment funding and transfers to an untracked account do not acquire a fabricated bank counterpart. They retain an explicit source classification when provided, or remain unresolved when evidence is insufficient.

## Step 2C.3: Category review

Show a queue for uncategorized transactions, suggestions needing review, and explicitly unresolved classifications. The inspector retains the original bank narration/category alongside the effective category, its provenance, and its review status. Offer a small fixed taxonomy appropriate to the fixtures: salary, interest, food/groceries, dining, shopping, utilities, housing, transport, health, subscriptions, bank fees, and other income/expense. Keep internal transfers, investment funding, refunds, and unresolved activity as distinct transaction roles rather than ordinary spending categories.

Suggestions come from transparent local fixture/rule evidence. Display the suggested category and reason, and allow accepting, choosing another eligible category, or leaving it unresolved. An automatic suggestion must not overwrite a manual decision. No merchant enrichment service, learned model, reusable rule editor, or external request is introduced.

Start with individual corrections, then a small bulk action for explicitly selected eligible rows. Before applying, show the exact selected count, current-to-new category changes, and excluded rows/reasons. Select-all applies only to visible results; changing filters clears the selection to prevent hidden-row changes. Validate the whole eligible selection before one atomic update. Announce completion, update queue counts, and offer Undo. Clearing a reviewed category returns the item to the appropriate unresolved state.

Direction and transaction role constrain the category choices: a credit cannot become an ordinary expense, and a confirmed transfer cannot be recategorized as groceries without first unlinking it. Investment funding remains excluded from consumption spending. Known bank fees remain eligible expenses. Unresolved money movements remain visible as unclassified coverage, rather than being forced into Other or silently counted as zero spending.

A verified sample refund retains its link to the original purchase and its refund role. It offsets the original purchase category once when computing classified spending for the refund's booking period; it is not income and does not rewrite the earlier debit. The paired category remains consistent after a correction or undo. Unlinked or excess refunds remain unresolved; a general refund-matching workflow is outside this increment. When showing a classified-spending preview, distinguish gross expenses, verified refunds, net classified spending, and unresolved coverage. Do not describe it as complete spending when records or decisions are missing.

Review changes survive app navigation but not reload. Include a clear local-demo notice and Reset sample decisions action, which resets decisions/selections and undo history while retaining immutable fixtures and display preferences. Populated/partial/loading/error demos preserve compatible decisions for still-present records; any pair with a missing member becomes unresolved as a whole, with an explanation. Empty/reset never leaves an orphaned pair or hidden selection. Do not persist review decisions or financial data in browser storage.

## Security and privacy

The prototype stays on loopback with bundled fictional data and existing browser security headers. No bank logins, passwords, account numbers, UPI IDs, real statements, file inputs, exports, network synchronization, backend/database work, or payment/transfer execution. The interface must distinguish review of recorded transfers from moving money.

Render descriptions, narration, references, and searches as text. Use friendly fabricated account/reference labels; no raw account identifiers in routes, logs, storage, screenshots, or errors. Known fixture IDs are the only accepted transaction route parameters. Review state is scoped to those known accounts and records, without implying server-side authorization exists.

Hide amounts must cover balances, debits/credits, filtered totals, pending totals, pair previews, reconciliation differences, category-change previews, undo/status messages, tooltips, and accessible labels. Source narration can itself contain amounts: when hidden, suppress the raw narration and reference in inspection, showing a neutral placeholder rather than attempting to redact arbitrary text with a numeric pattern. Merchant labels and categories may remain visible, consistent with the existing display-privacy boundary. Bundled data remains inspectable; masking is not authentication or encryption.

Keep search, filters, selections, candidate decisions, category corrections, and undo history in memory. Only the existing display preferences persist. Do not introduce telemetry, remote assets, clipboard/export shortcuts, or financial content in the URL. Future production review requires authenticated ownership checks, durable audited corrections, ingestion validation, reconciliation, and recoverability under the [security requirements](security.md).

## States and acceptance evidence

| Area | Required evidence |
| --- | --- |
| Balances and accounting | Full-period opening/posted movement/closing reconciliation; shared Overview bank balances; cash counted once; pending items excluded; partial gaps reported without invented adjustments. |
| Activity controls | Combined filters, inclusive date boundaries, timezone independence, literal search, stable numeric sorting, repeated same-amount transactions preserved, no-matches versus no-data distinction, and unchanged snapshot balances. |
| Transfer integrity | Unique/ambiguous/unmatched cases, same-account/pending/unequal/cross-currency rejection, counterpart outside filters, no reuse, repeated actions, atomic unlink/undo, missing-leg handling, and unchanged ledger totals. |
| Categories | Suggestion versus manual provenance, direction/role restrictions, explicit bulk selection and exclusions, no hidden-row updates, verified refund treatment, unresolved coverage, reset, and reversible corrections. |
| Navigation | Desktop/mobile inspection, direct/invalid routes, browser history, retained controls and scroll, focus restoration, drawer/dialog keyboard containment, Escape, and no dead controls. |
| Privacy | No masked-value leaks in DOM, narration, references, tooltips, accessible labels, live announcements, or review history; plain-text rendering; no financial values/searches/decisions in URLs or browser storage. |
| Demo states | Populated, loading, empty, partial/stale, and failed load; failure retains the last usable records and compatible decisions; retry recovers locally without duplication. No matches, no candidates, and fully reviewed queues have distinct empty states. |
| Visual/accessibility | Both themes at 1440, 768, and 390 px; 320 px reflow; long descriptions and large amounts; keyboard and contrast checks. Revisit enlarged text/400% zoom, reduced-motion preference, and screen-reader limitations and record what was actually tested. |
| Engineering | Targeted pure-data and component tests, existing Overview/Investments regressions, TypeScript, production build, local asset/security-header checks, dependency review if changed, and synthetic screenshots. |

Record actual results in the [prototype implementation notes](ui-prototype.md) as each increment is delivered. Planned targets are not completed checks or a claim of production security.
