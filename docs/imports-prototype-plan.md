# Import review and connection status prototype plan

Status: Step 2D is merged into `main`. Steps 2E.1–2E.4 below are planned; no import or connection UI is implemented by this document. See the [current prototype](ui-prototype.md), [integration research](integrations.md), and [security requirements](security.md).

The next screens should explain where records come from, what periods they cover, what an incoming batch would change, and why some records need review. Security and financial accuracy take priority over automation. Continue the Indigo & Apricot themes, shared INR/USD and privacy controls, visible sample labels, and loopback-only runtime.

## Delivery increments

| Increment | Deliverable | Status | Conventional commit |
| --- | --- | --- | --- |
| 2E.1 | Connections workspace, source coverage/details, and simulated status/recovery walkthroughs | Planned | `feat(connections): add source status walkthrough` |
| 2E.2 | Bank sample catalog, batch previews, issue summaries, and original/normalized row inspection | Planned | `feat(imports): add bank statement review previews` |
| 2E.3 | Reversible bank review decisions, duplicate/conflict handling, reconciliation, and sample review completion | Planned | `feat(imports): add reversible sample review decisions` |
| 2E.4 | Investment review examples for INDmoney, mutual-fund overlap, and UBS employee shares | Planned | `feat(imports): add investment statement walkthroughs` |

Each increment includes meaningful tests, documentation, and fictional light/dark desktop/mobile evidence in a focused `dev` to `main` PR. Features scheduled for later increments remain visibly planned until functional. Activity remains outside Step 2E.

## Prototype boundary

Use bundled, already normalized fictional examples. There are no file pickers, drag-and-drop targets, clipboard imports, PDF passwords, document downloads, parsers, mailbox access, provider sign-in, tokens, real network connections, or background jobs. A sample format label illustrates a possible source; it does not establish support for a provider's actual export format or account permissions. Provider feasibility remains subject to the separate integration work.

Selecting a sample opens a proposed-change review. Completing it produces an in-memory review receipt with explicit **Sample only — no records saved** language. It must never insert, delete, replace, or reclassify records in Overview, Investments, Banking, Budgets, cash flow, or recurring review. A connection simulation also cannot change those screens' source dates or coverage. The production receive/parse/validate/commit process in [architecture](architecture.md#imports-and-reconciliation) remains separate work.

Keep original sample evidence immutable and preserve provenance beside review decisions. Existing ledger/holdings collections remain authoritative for financial screens. Any comparison baseline used by a walkthrough is explicitly labeled, versioned, and isolated from live screen state; do not present it as a second current portfolio.

## Workspace and navigation

Enable Connections at `#/connections` in 2E.1. Use Sources and Sample imports views inside this workspace; the latter becomes interactive in 2E.2. Source cards with an implemented example can open its sample review. Other cards explain the available demonstration without offering a working-looking unsupported action.

Batch details use allowlisted opaque routes such as `#/connections/imports/i01`. Incoming row inspection stays within its batch and clearly distinguishes incoming source fields, normalized fields, matched existing evidence, and review decisions. Existing record links can use the current bank/holding inspector when their IDs are known. Back, Forward, Close, and return links restore the originating source/batch, filters, selected row, scroll, and focus; use a section-heading fallback when that target is unavailable. Reload starts the appropriate known fixture in its initial review state. Unknown routes/IDs show an unavailable screen.

Desktop uses a compact source/status summary, a filterable review list, and a focused detail area. Mobile stacks the same information into cards and puts the primary action after its consequences. Use explicit text statuses and icons, tabular amounts, named controls, and a visible current step rather than color-only indicators. Keep account mapping, period coverage, unresolved blockers, and the next useful action near the relevant content. Never present a progress indicator as a real upload or provider sync.

Only existing display preferences persist. Routes contain opaque allowlisted IDs, never filenames, account/folio identifiers, searches, amounts, permissions, or review decisions. Filters and navigation context stay in memory.

## Step 2E.1: Connections and source coverage

Show six source groups matching the existing sample accounts: INDmoney India, INDmoney US, advisor mutual funds, UBS Accenture ESPP, HDFC, and SBI. Distinguish the institution/source group from its individual account and data stream; holdings, activity, cash, prices/NAVs, and FX may have different sources and dates.

| Information | Required behavior |
| --- | --- |
| Current mode | State **Bundled sample** and **No provider connected**. Manual statement examples and simulated connector scenarios are distinct. |
| Data coverage | Show supplied account/period coverage and known gaps. Distinguish a full month, month-to-date, stale snapshot, missing stream, and never supplied. |
| Freshness | Separate last simulated attempt, last simulated successful receipt, financial data as-of date, statement period, and price/NAV/FX date. A successful attempt does not make old records current. |
| Permissions | Separate illustrative permissions from verified provider capabilities. Automatic access and actual scopes remain unverified; never label a provider read-only solely because this UI has no trading controls. |
| Status | Treat authorization, last attempt outcome, and data coverage as separate facts. A successful attempt can return partial or stale data. |
| Failure guidance | Explain the affected stream and retained source dates; offer only a local action relevant to the supplied scenario. No raw provider errors, credentials, or payloads. |

Use supplied scenarios for available data, never received data, refresh in progress, stale/partial results, transient failure, rate limiting, expired/revoked illustrative authorization, and a statement-only source. HDFC/SBI/UBS/advisor statement examples have no invented OAuth status. Any connector authorization example is prominently simulated and is not evidence that a real integration exists.

Actions such as **Run sample refresh**, **Retry sample attempt**, **Simulate access renewal**, and **Reset sample connection states** operate only on bounded fixture transitions. A transient failure can retry; expired/revoked access requires its explicit simulation step before a successful sample attempt. A rate-limited scenario explains its supplied retry condition without live countdowns or scheduled retries. Repeated clicks during an attempt cannot create overlapping runs. Never show real Connect, Sign in, Disconnect, or credential-entry flows.

Use explicit fixture timestamps and deterministic scenario outcomes, not the current wall clock. A sample receipt has its own evidence dates; retrying does not silently replace the underlying financial snapshots or manufacture a newer price. A small attempt history can explain the latest outcome, but it is neither a production audit log nor proof of provider access. Reset affects only connection walkthrough state.

## Step 2E.2: Bank import previews

Add a small HDFC/SBI sample catalog and a read-only batch review flow: **Choose sample → Inspect source and rows → Review issues**. Each batch identifies its fictional source, account, owner, statement period, source revision, original currency, row count, and supplied opening/closing balances where available. Describe the examples as illustrative statement data rather than tested CSV/PDF parsers.

Use fixtures for a reconciling batch, exact replay, partial overlap, legitimate repeated payments, a conflicting source identity, a missing/invalid field or ambiguous date, an account/owner mismatch, and incomplete/non-reconciling coverage. Cases can share a bounded fixture family; do not generate arbitrary financial history. Supply independent expected counts, amounts, and balances with the fixtures and document known results before displaying them.

Each incoming row has a stable batch/row identity independent of its array position and proposed transaction identity. Preserve original supplied text alongside normalized direction, native amount/currency, booking date, optional value date, status, account, and source reference. Use explicit fixture date formats; ambiguous dates are not guessed. Invalid amounts are unavailable, not zero. Row inspection explains both the issue and supporting evidence without modifying the source.

| Row disposition | Preview meaning |
| --- | --- |
| New candidate | A supported record with complete identity/required fields that is not already in the comparison baseline. |
| Already present | Exact source evidence matches an existing record; show the match and propose skipping, without adding its amount again. |
| Duplicate within batch | Identical scoped source identity and immutable fields repeat inside the sample. Link the canonical incoming row; propose including it at most once. Different fields under the same identity are a conflict. |
| Possible overlap | Similar records need interpretation. Date, payee, and amount alone do not prove a duplicate. |
| Conflict | A stable source identity exists with different immutable fields. Preserve both versions for inspection; do not silently overwrite. |
| Invalid / unsupported | Required identity, date, currency, amount, precision, or record-kind checks fail. Explain the specific blocker. |

Provide filters for disposition, account, and a bounded literal search over fictional descriptions/references. Keep whole-batch counts and coverage distinct from filtered results. A row-count identity must account for every source row exactly once. Monetary summaries group by original currency and posted/pending status; mixed-currency totals require explicitly labeled display conversion rather than native reconciliation through FX.

This increment provides inspection only. Resolution and completion controls remain planned until 2E.3; no enabled button should appear to save an import.

## Step 2E.3: Review decisions and completion

Add explicit per-row decisions for **Include candidate**, **Skip as duplicate** with its evidence link, **Exclude from this sample review** with a fixed reason, and **Restore row decision**. A possible overlap may be treated as a distinct record only when the supplied evidence supports separate identities; otherwise it remains blocked. Demonstrate the existing same-day café payments as distinct records, not a reason to deduplicate equal amounts.

Allow account mapping only among known compatible sample accounts owned by the same sample owner, where supplied source identity supports that mapping. Institution name alone is insufficient. Do not create accounts, change ownership, guess a folio, or convert an invalid record into a valid one through mapping. Missing identity, malformed values, source conflicts, and unsupported types have no arbitrary correction editor. A batch can be set aside and reopened; excluding its essential evidence does not make it reconciled or ready.

Use one independent in-memory import-review history with Undo review change and Reset sample import reviews. Every decision retains its original row, prior choice, reason, and matched evidence. A decision change invalidates any existing completion preview/receipt for that batch. Reopening a completed sample review makes its status explicit before further edits. Banking/category/transfer histories, budget limits, recurring decisions, and connection walkthroughs retain their own reset boundaries.

### Identity, duplicates, and stale decisions

- A supplied sample fingerprint/revision identifies an exact batch replay; it is not a hash of a real uploaded file. Real hashing and collision handling belong to ingestion implementation.
- Scope source transaction identity to the known owner/account/provider and source-defined identity rules. Reject duplicate conflicting IDs within a batch as well as conflicts with the comparison baseline.
- Whole-batch identity and row-level overlap are different checks. Distinct files can contain the same transaction; repeated amounts/dates/payees can describe different transactions. Preserve both legitimate repeats and separate accounts.
- Each source row receives one disposition; one existing record cannot silently satisfy multiple incoming occurrences. A skipped duplicate contributes no additional movement or units.
- Bind every proposed action to the batch/row revision, immutable fields, current mapping, matched baseline identity, and current decision. Revalidate before applying or completing; stale/conflicting evidence fails visibly without partially changing decisions. A changed baseline requires a fresh preview.
- Completion is idempotent for the same batch revision and decision set. Replaying or retrying a completed review must not append duplicate receipts or outcomes. These checks model a future import boundary; they are not durable database idempotency or authorization.

### Reconciliation and review receipt

Keep source-statement reconciliation separate from the proposed incremental effect. Validate the full source statement against its independently supplied opening/closing balances. Then compare the combination of retained baseline entries and proposed unique entries over the same account/currency/period; already-present rows appear once. A date-limited filter must not change either result.

For bank records, use exact minor units and `opening + posted credits − posted debits = closing` where the supplied coverage supports that identity. Keep pending amounts separate. Include transfers and investments as bank movements without calling them spending. Preserve both transfer legs and separate fees; import review never automatically pairs transfers, changes spending categories, or confirms a recurring pattern.

Unknown openings/closings, incomplete periods, incompatible currencies, unresolved identity/mapping, mandatory-field errors, unsupported records, and unexplained reconciliation differences block **Complete sample review**. Explicitly omitting necessary rows cannot clear those blockers. Do not manufacture an adjustment to make a batch balance. A purely informational warning may be acknowledged only when it has no unresolved effect on identity, amounts, coverage, or reconciliation.

The final review summary shows included, already-present, excluded, and unresolved counts; reasons; native-currency proposed movements; reconciliation and coverage; and the explicit sample-only effect. Confirming completion records the batch/revision and decision summary in memory and shows **Sample only — no records saved**. Completion requires visible amounts so the user can inspect consequences; masking dismisses the completion preview and disables completion until amounts are shown again. Cancel returns to review unchanged. No financial row becomes committed to the application.

## Step 2E.4: Investment statement walkthroughs

Extend the same catalog, evidence inspection, review decisions, and receipt behavior to a bounded set of INDmoney India/US, mutual-fund, and UBS examples. These are generic normalized statement scenarios, not claims about accepted provider file layouts. Unsupported events remain visibly outside the walkthrough rather than silently normalized.

| Scenario | Identity and reconciliation requirements |
| --- | --- |
| Indian/US stock and ETF snapshot | Identify owner/account/instrument separately; ticker/name alone is insufficient. Preserve fractional units and original currencies. A snapshot is not a trade ledger. |
| Mutual-fund overlap | Show the same folio represented through INDmoney and a consolidated statement. Keep scheme identity, direct/regular plan, growth/distribution option, holding form, owner/account, and folio evidence distinct. Incomplete mapping stays unresolved. |
| Advisor regular funds | Keep regular-plan holdings separate from similarly named direct-plan holdings. Do not move or merge them based on name or apparent lower cost. |
| UBS Accenture ESPP | Reconcile the supplied remaining lot units to the supplied UBS position; preserve source purchase amounts, fees, dividends/withholding, and dates independently. Missing acquisition or tax-basis fields remain unknown. |
| Cross-account security | The same security at INDmoney US and UBS remains separate ownership positions; it is not an import duplicate. |

Explicitly type each input as a holdings snapshot, activity record, cash record, or lot record. Snapshot overlap can select a bounded source preference for the same identity/date inside the review, with both versions retained; conflicting units or identity remain blocked; selecting a preferred source cannot override a mismatch. Preferences for one account or data stream do not become a global provider ranking.

Use existing exact unit/quote scales and monetary helpers. Reject unsupported precision before conversion; apply documented rounding only where valuation requires it. Validate units per account/instrument/folio and money per native currency. If complete opening units, supported activity, and closing units are supplied, reconcile them; otherwise label the available snapshot checks and the missing activity history. A snapshot-only review may complete when its explicitly narrower identity/position checks pass, without claiming transaction reconciliation or complete lots/history. An activity/lot batch requiring absent openings or unsupported corporate actions remains blocked.

Never invent trades to explain a position difference, net different currencies to hide a mismatch, add cash twice, or reconstruct cost from current value. Current demo FX is display-only and is not historical acquisition FX or tax basis. No performance, tax, ESPP benefit valuation, corporate-action engine, trade execution, or change to the existing investment totals is included.

## Shared security, privacy, and state rules

Treat source descriptions, references, filenames, mapping labels, and error text as untrusted plain text even in fixtures. No HTML execution, arbitrary URLs, external logos/fonts, console payload dumps, financial values in routes/storage, or new dependency is needed by default. Validate bounded literal searches, enum choices, known source/row IDs, owner/account mappings, and numerical/date inputs. Client fixture checks never substitute for production authentication, server authorization, isolated parsing, durable audit history, or database transactions.

INR/USD applies to every primary monetary preview, difference, receipt, and source detail. Retain explicitly labeled native amounts for reconciliation; keep canonical arithmetic independent of display rounding. Hide amounts removes values, quantities, quotes, ranges, raw text containing financial values, accessible labels, previews, receipt details, and amount-dependent geometry from the DOM. Status/count announcements contain no amounts. Masking clears pending action/completion previews and disables decisions that affect proposed amounts, units, or mapping, as well as completion. Inspection, filtering, explicit undo, and domain reset remain available; financial content stays hidden. Masking remains visual privacy, not access control.

| State / action | Required behavior |
| --- | --- |
| Populated / partial | Keep compatible local decisions. Validate changed/missing evidence on every affected preview; retain incompatible decisions as Needs review and block completion. |
| Loading | Hide financial totals, disable actions, and clear pending completion/action previews. Retain compatible drafts in memory for the next usable snapshot. |
| Failed load / retry | Retain the last usable snapshot and decisions with explicit source dates. Retry does not imply success or duplicate records/receipts; status distinguishes no prior snapshot from retained data. |
| Empty / restore sample | Clear local planning/review selections consistently with the existing global empty-state behavior; restoring fixtures starts initial source/import scenarios and financial review defaults. |
| Domain reset | Reset sample connection states affects only connection scenarios; Reset sample import reviews affects only import decisions/receipts. No reset changes original source evidence. |
| Reload | Reset walkthrough scenarios, drafts, receipts, history, filters, and selection. Preserve only existing display preferences. |

Use fixed sample evidence dates consistent with the existing sources: October banking coverage ends at 20 October, 10:00 IST, while investment snapshots/prices retain their separately supplied dates. New walkthrough timestamps/periods must be documented as supplied evidence; do not imply all streams share a single freshness time. Navigation between views must not reset another domain's local work.

## Acceptance evidence

| Area | Required evidence before its increment is complete |
| --- | --- |
| Connection honesty | Sample-only labeling; separate permission, attempt, receipt, and as-of states; stale/partial success; expired/revoked access; rate limits; bounded retry; statement-only sources without invented consent; independent resets. |
| Bank review | Exact row-count accounting, posted/pending separation, independent native reconciliation, already-present rows counted once, legitimate repeats, cross-account distinction, conflicting source IDs, invalid/missing fields, unknown coverage, and exclusions that cannot hide blockers. |
| Decision integrity | Revalidation of revision/mapping/matches/previous decision, no partial actions, stale completion rejection, replay/retry idempotency, undo/restore, completion invalidation on edits, and isolated review receipts. |
| Investment evidence | Snapshot/activity/lot separation, fund plan/folio/option mapping, same holding across sources versus same security across accounts, exact fractional units, missing prices/basis/history, lot totals, and no invented trades. |
| Financial invariants | Overview assets, investment positions, all six bank statement reconciliations, monthly budgets, cash flow, category/transfer decisions, and recurring expectations remain unchanged after walkthrough actions within the same global demo state. Test the known full/partial baselines and independent undo/reset boundaries; global empty/restore retains its existing reset contract. |
| Privacy and security | Hidden amounts/units/raw text absent from DOM, attributes, accessible names, messages, URLs, storage, and logs; plain-text rendering; no file/credential entry or external calls; loopback headers and local assets retained. |
| Navigation and states | Direct/invalid routes, browser history, source/row inspectors, return focus and fallback, preserved filters/scroll, loading/empty/partial/error/retry, cancellation, reset, and reload. |
| Visual and accessibility | Indigo & Apricot light/dark at 1440, 768, and 390 px; 320 px reflow; long labels/large values; keyboard flow, dialog containment, focus, contrast, and primary touch targets. Revisit actual enlarged-text/400% zoom, reduced motion, and screen-reader checks; record limitations honestly. |
| Engineering and docs | Relevant data/component tests plus existing regressions, TypeScript/build, dependency/license review if changed, actual screenshot evidence, documented fixtures/results, and final diff review. Planning-only changes require documentation/link/whitespace checks, not unrelated application tests. |

Record implemented behavior, known fixture outcomes, verification, and remaining limitations in [prototype notes](ui-prototype.md) as each increment is delivered. Real imports and connections depend on the later Python/security/data foundations; this plan does not activate those capabilities.
