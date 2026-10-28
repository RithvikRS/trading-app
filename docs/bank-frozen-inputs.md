# Frozen bank comparison inputs: Step 8A.4

Protected Banking opens the retained opening, activity and closing inputs behind a selected bank cash comparison. Each source-report or combined-evidence group is chosen explicitly. Original values, dates, posting states and reference revisions describe the completed historical operation; they do not select a current balance or establish complete bank history.

## Selection and source binding

The six input actions extend [saved bank comparisons](bank-cash-comparisons.md) using the existing protected `/receipts/inputs/query` read. Before displaying a page, the projection revalidates the saved comparison against the selected HDFC/SBI account, declared native currency, exact receipt, period, date basis and originating source posting floor. Other-account and position scopes remain visible as batch metadata without gaining input inspection from Banking.

The existing [frozen-input contract](frozen-input-inspection.md) validates the entire response, exact allowed fields, reference kind, scope, side, part, dates and revisions. Source rows retain their review revisions; combined activity retains event revisions; combined checkpoints retain snapshot revisions. Matching originating references must preserve their exact revisions. This inspection does not retrieve or replace those references with their current values.

Pages contain at most 25 inputs. Only current-page values, an opaque cursor and bounded count metadata are retained. Expected input totals and posted/pending counts bind to the saved comparison. Refresh uses the preceding-page counts; next uses the accepted current counts. Switching sides/groups or choosing the first page resets traversal. A genuinely empty activity group remains empty, while a missing opening/closing checkpoint fails validation.

## Exact values and interface

Cash remains in the bank account's declared INR or USD currency, independently of the display-currency preference. Original decimal spelling, negative values and negative zero remain intact. Missing or malformed required cash evidence is rejected rather than replaced by zero. Pending rows remain distinct and never become posted movement; their evidence date may be absent when the retained contract permits it.

Compact cards keep native values and dates visible with expandable source references. Both themes use the existing Indigo & Apricot styles, keyboard focus restoration, labeled selectors and touch controls. Masking covers values in visible and accessible content. Opening an input page clears the earlier equation display, and returning refetches its original comparison scope.

## History consistency and privacy

Bank event history separately retains the highest revision already accepted during the current navigation. The original clicked identity and selected historical payload remain unchanged. Refresh, earlier/latest navigation and source/receipt/input returns preserve this scalar floor; a subsequent first-page response claiming a lower head is rejected. This is defensive detection of a contradictory response, not evidence of a supported database concurrency flaw. Explicitly leaving the event context discards its local state.

The existing active MFA/session, same-origin POST/CSRF, owner isolation, no-store response and response-size boundaries remain in force. Protocol inconsistencies lock the workspace before partial values are shown. Unavailable nested reads clear bank, origin, receipt, comparison and input context; explicit recovery starts at a fresh account directory. Navigation, lock, sign-out and session replacement discard late responses. No input values are written to browser storage or URLs.

Row-effects-only receipt navigation stays restricted. Full investment comparison/input inspection retains its existing behavior. This increment adds no backend route, schema, dependency, financial write, acquisition, selection, transfer/category inference or current-balance calculation.

## Verification

Synthetic regression sources cover all six selections, INR/USD preservation, exact checkpoint spelling, pending and zero semantics, ownership/scope mismatch rejection, malformed whole-page rejection, bounded pagination/refresh, unavailable/protocol clearing, late responses, masking, keyboard behavior and separate highest-seen history floors. 80 focused tests passed; the affected nine-suite run passed all 644 tests, including the 80 focused cases. TypeScript and both production builds passed. Synthetic Chromium at 1440px and 390px in light/dark modes exercised all six input actions, native INR/USD values, masking, 25+1 pagination/refresh, nested returns, 409 recovery and protocol/history rejection. Keyboard and disclosure checks, 44px controls, preview security headers and protected CSRF requests passed. Axe WCAG/contrast checks found no violations or horizontal overflow; browser storage remained empty and sign-out cleared the view. All 12 captures were inspected, and the owned preview/browser were stopped with port 8037 closed.

The initial focused run retained 79 passes and one test-only failure: its expected ungrouped `INR 1000` did not match the existing formatter's `INR 1,000`. Correcting that expectation yielded 80 passes. No product behavior, assertion coverage, deadline or isolation setting was relaxed. The affected run retains the existing jsdom canvas notices; the demo build retains its chunk-size warning. Real statements, provider compatibility, hosted authentication and deployment remain unperformed. The final integrated local verification remains separate.


## Captures

Synthetic records only.

| View | Desktop light | Desktop dark | Mobile light | Mobile dark |
| --- | --- | --- | --- | --- |
| Six explicit input choices | [1440px light](images/bank-frozen-inputs/choices-1440-light.png) | [1440px dark](images/bank-frozen-inputs/choices-1440-dark.png) | [390px light](images/bank-frozen-inputs/choices-390-light.png) | [390px dark](images/bank-frozen-inputs/choices-390-dark.png) |
| Source activity and pending evidence | [1440px light](images/bank-frozen-inputs/activity-1440-light.png) | [1440px dark](images/bank-frozen-inputs/activity-1440-dark.png) | [390px light](images/bank-frozen-inputs/activity-390-light.png) | [390px dark](images/bank-frozen-inputs/activity-390-dark.png) |
| Combined historical checkpoint | [1440px light](images/bank-frozen-inputs/checkpoint-1440-light.png) | [1440px dark](images/bank-frozen-inputs/checkpoint-1440-dark.png) | [390px light](images/bank-frozen-inputs/checkpoint-390-light.png) | [390px dark](images/bank-frozen-inputs/checkpoint-390-dark.png) |
