# Saved bank cash comparisons: Step 8A.3

Protected Banking can inspect saved native cash comparisons from reconciled import receipts. These opening, movement and closing equations describe evidence frozen at completion. They do not provide a current bank balance, a selected snapshot or complete account history. Limited receipts retain their row effects without offering a comparison.

## Scope and source binding

The scope list retains every comparison in the receipt, including other accounts and position units. Only native cash scopes belonging to the selected HDFC/SBI bank account are inspectable here. Other-account metadata remains visible with its original page cursor. A selected-bank position/unit scope or an undeclared currency fails closed; it is never silently filtered out. Both INR and USD are valid when declared by the selected account.

All scope periods bind to the clicked event's source observation. Cash scopes also bind to the originating batch's booking, value or settlement date basis; position-unit scopes retain trade dates. Opening comparison inspection requires an active complete-activity origin with a supplied native cash currency and explicit period/basis. No amount strings are retained in navigation context.

Pages contain 25 records. Count-only progress and two native-currency flags validate the complete receipt total, require the originating bank/currency scope once at traversal completion, and reject duplicated selected-bank currency scopes across pages. A first page containing only other-account scopes remains usable. Refresh uses preceding-page progress, while next uses current progress; first/back navigation resets and refetches.

## Exact historical equations

The shared strict comparison projection verifies original decimal strings with exact scaled integers. Source and combined opening/closing boundaries agree; opening plus posted movement equals closing, calculated closing matches and the difference is zero. Posted and pending counts remain separate, and pending entries do not enter the posted movement. Cash may be negative or zero. Original decimal precision remains visible and the display currency preference does not convert it.

The source activity count plus two distinct checkpoints cannot exceed the receipt's source-row count. The complete input count must equal the four source/combined checkpoints plus both sides' activity counts. The originating currency's source posted or pending count must include at least the clicked source occurrence's posting state. That lower bound does not imply individual input lineage or combined-side inclusion. A different native currency does not inherit the origin's activity-count lower bound.

Bank comparison mode is distinct from full investment inspection and from row-effects-only mode. Step 8A.3 adds the existing scope query and comparison inspection routes. [Step 8A.4](bank-frozen-inputs.md) subsequently adds explicit frozen-input inspection for the selected bank cash scope; standalone dated snapshot/selection inspection remains separate work. Full investment and lot comparison/input navigation stays available.

## Privacy and recovery

Masking covers every financial value, including zero and negative amounts, both equations and their calculated closing/difference. Technical references are expandable. Loads drop old values; stale navigation, lock, sign-out and replacement-session responses are discarded. Protocol inconsistencies block the workspace. Unavailable nested reads clear account, origin, receipt and comparison context through the required bank parent reset; explicit retry begins with a fresh account-directory read. Returning to history refetches while preserving the known revision floor.

No backend, schema, dependency, provider or financial mutation changes are introduced. No real bank statement or format compatibility is claimed.

## Verification

The retained focused run passed 134 tests: 70 bank comparison cases and 64 provenance cases. It covers native scope/period/basis binding, exact arithmetic, source posting and row-capacity bounds, mixed-account traversal, refresh progress, duplicate currencies, history return floors, all unavailable/protocol reset paths, late responses and replacement sessions. Its log and exit receipt survived in a separate checkpoint, and the restored production/test files match their recorded hashes. Other earlier local logs became unavailable after worktree/cache loss; their historical results are not used as fresh verification.

Fresh serial compatibility verification first passed 299 cases, with one existing Banking keyboard failure; two other suites did not start because their test workers timed out. The unchanged keyboard case then passed alone. A complete seven-suite rerun reached all 454 cases: 453 passed and an existing event-completion receipt case exceeded its 5000ms limit. That unchanged receipt case then passed alone. No source, assertion, guard, timeout or worker-isolation changes were made. The failures and separate passes remain recorded; their exact causes were not established, and these runs do not constitute a passing combined 454-case run. The final integrated local gate remains required. TypeScript and both production builds passed against the same source.

Fresh synthetic Chromium checks passed at 1440px and 390px in light and dark modes, with keyboard navigation, expandable source cards, minimum 44px controls, zero WCAG A/AA automated violations including contrast, no horizontal overflow, all ten financial values masked, native display semantics and sign-out clearing. Separate probes cover a 25-plus-1 mixed-account traversal, malformed period rejection, unavailable-read reset to a fresh account directory, an otherwise balanced response violating the source posting floor, and older-source navigation preserving the revision floor. No input or snapshot requests were issued. The browser and exact owned loopback preview were stopped, and the port was verified closed.

All eight refreshed captures were visually inspected. Interaction and accessibility checks use a 1000px-high viewport; capture height alone expands to contain the full section, with the unfocused skip link verified offscreen. The compact scope list measures 1167px on desktop and 1398px on mobile; equations measure 1066px and 1641px respectively. No product CSS is changed for capture. An initial test invocation was rejected by the npm wrapper before tests ran, and the first browser attempt stopped before launch because the pinned test binary was absent. Direct runner invocation and installation of the local pinned headless browser resolved those tooling prerequisites without product dependency changes.

| View | Desktop light | Desktop dark | Mobile light | Mobile dark |
| --- | --- | --- | --- | --- |
| Saved comparisons | [Capture](images/bank-cash-comparisons/scopes-1440-light.png) | [Capture](images/bank-cash-comparisons/scopes-1440-dark.png) | [Capture](images/bank-cash-comparisons/scopes-390-light.png) | [Capture](images/bank-cash-comparisons/scopes-390-dark.png) |
| Native equations | [Capture](images/bank-cash-comparisons/equations-1440-light.png) | [Capture](images/bank-cash-comparisons/equations-1440-dark.png) | [Capture](images/bank-cash-comparisons/equations-390-light.png) | [Capture](images/bank-cash-comparisons/equations-390-dark.png) |
