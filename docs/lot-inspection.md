# Protected lot-evidence inspection: Step 7B.1

The protected investment detail now opens saved lot identities, their acquisition/remaining observations and revision history. The view uses the existing [event and lot read APIs](event-lot-reads.md); it adds no financial mutation, provider access, statement parser, migration or live UBS compatibility.

## Evidence and navigation

Choose a saved investment position and select **Inspect lot evidence**. A position can have lot evidence even when no holdings snapshot is selected. Identities contain no quantity. Open a lot to inspect the latest revision of each independent observation, including cancellations, then inspect one observation's retained revision history.

Each request is limited to 25 rows. Lot/observation lists use opaque identity cursors; history uses descending revisions. First/next or latest/earlier navigation replaces the previous page. These are live reads, so reload the first page to discover newer evidence. Empty results mean evidence is absent on that page, not zero holdings or complete history.

Acquisition observations show original quantity; remaining-lot observations show supplied remaining quantity. They are not added or automatically selected. Purchase cost, monetary discount and reported tax basis retain their separate source roles and currencies. Missing values keep their supplied reason; an absent optional component is labeled as not supplied by that observation. A zero remaining quantity does not identify a sale.

Acquisition, observation and booking dates remain independent. Source coverage and its supplied period are inspectable alongside the original source/observation/batch/row and review revision. Coverage is a source claim, not a reconciled receipt or lifetime history. Current revision means no later revision exists, not that the evidence is fresh or complete.

Corrections preserve earlier values. Cancellation has no components and creates no synthetic reversal or zero balance. History identifies source corrections, cancellations and reinstatements. The screen calculates no disposal allocation, remaining balance, tax basis, gain or return.

## Privacy and correctness

Requests use the existing authenticated MFA, CSRF and workspace-context boundary. Responses must match the selected position, account, instrument and lot; history must match the selected observation and scope. The first history page cannot regress below the revision used to open it; equal or newer revisions and genuinely older cursor pages remain valid. Malformed identity, status, revision, dates, values or pagination lock the workspace instead of attaching evidence to the wrong investment. Unknown/foreign responses inherit the existing generic server failure behavior.

Financial decimal strings remain exact through parsing and display, including trailing zeros and fractional shares. INR/USD is a display preference only: this view retains native evidence and explains that conversion and current valuation are unavailable. Mixed-currency components are never combined.

Masking removes quantity and monetary text, including known zero and missing-value details, from both visible and accessible content. No amount is encoded in a label, URL, chart or geometry. Navigation keeps only bounded view state in memory. Loading or failed reads clear previous amounts; lock, sign-out and workspace replacement discard the view and late responses. There is no automatic retry or browser persistence.

The protected view includes no fabricated portfolio fallback. Synthetic observations exist only in [tests](../frontend/src/test/workspace-lots.test.tsx), alongside the existing protected investment tests. The separate prototype is unchanged.

## Implementation and checks

[Lot response projections](../frontend/workspace/src/lot-evidence.ts) validate exact components, parent relationships, source periods, cancellation semantics and bounded current/history pages. [LotInspection](../frontend/workspace/src/LotInspection.tsx) renders the read-only view and uses the existing design tokens and responsive evidence layout.

Focused tests cover native exact values, acquisition versus remaining scopes, unknown versus zero, correction/cancellation history, first-page revision regression and clear-on-block behavior, all three cursor paths, malformed/foreign responses, unavailable reads, masking, structural accessibility and late-response disposal. Run the lot and investment test files with TypeScript checking, followed by the [standard verification groups](verification.md) for integration.

This is application behavior over saved evidence. [UBS feasibility](ubs-integration-plan.md), actual API/export contracts, complete-history acquisition and production workload verification remain separate work.

On 25 October 2026, the two focused lot/investment files passed 72 tests, including four revision-boundary regressions. TypeScript and both demo/protected production builds passed. The original synthetic browser checks at 1440 px and 390 px passed in both themes: keyboard entry and focus, exact native values under both display preferences, masking of visible/accessible amounts, source-limited evidence, correction history, WCAG 2.0/2.1 A/AA checks including contrast, horizontal reflow, empty local/session storage and sign-out clearing. These checks used fabricated responses against a local static build; they do not verify hosted authentication or UBS access. The integrated revision still receives the standard verification groups before merging.

| View | Desktop light | Desktop dark | Mobile light | Mobile dark |
| --- | --- | --- | --- | --- |
| Current observations | [1440 px](images/lot-inspection/observations-1440-light.png) | [1440 px](images/lot-inspection/observations-1440-dark.png) | [390 px](images/lot-inspection/observations-390-light.png) | [390 px](images/lot-inspection/observations-390-dark.png) |
| Correction history | [1440 px](images/lot-inspection/history-1440-light.png) | [1440 px](images/lot-inspection/history-1440-dark.png) | [390 px](images/lot-inspection/history-390-light.png) | [390 px](images/lot-inspection/history-390-dark.png) |
