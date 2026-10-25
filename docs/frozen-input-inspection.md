# Frozen comparison inputs: Step 7B.4.2

The [native comparison inspector](frozen-comparison-inspection.md) now exposes the retained rows behind each historical equation through the existing [protected input read](completion-receipt-reads.md). No acquisition, financial mutation, backend route, schema or dependency is added.

## Scope and navigation

Each Source report and Combined saved evidence card offers opening, activity and closing inputs. These are six explicit selections. The selected scope remains authoritative, including other accounts or positions within the receipt. One selection is loaded at a time in 25-row reference-identity order, not date order. Side/group changes reset the cursor and replace the prior rows; earlier pages and selections are not cached. Returning to the comparison refetches its validated equation.

Inputs show the native value, original evidence date and activity posting state. Opaque identities and retained revisions are in expandable source details. Source occurrences retain review-decision revisions; combined activity retains event revisions; combined checkpoints retain snapshot revisions. These are original completion inputs, not current records. Missing pending dates stay unknown. No current balance, tax basis, FX conversion, return or complete-history conclusion is calculated.

## Exact checks and privacy

[Input projections](../frontend/workspace/src/input-evidence.ts) enforce the exact response keys, scope/side/part/native binding, canonical nonzero identities, safe positive revision numbers and unambiguous lineage. Values preserve plain decimal spelling, sign and trailing zeros within the existing 32-character/magnitude bounds: cash has at most two fractional places and units twelve. Unit checkpoints are nonnegative; explicit negative zero remains source evidence.

Opening and closing each require one input at the corresponding period boundary, with the exact same-side checkpoint lexeme. Posted activity requires a supplied date within the period. Pending activity can omit its date, but a supplied date must also lie within the period, as required by the persisted completion guard. Pending rows remain visible and excluded from the posted movement.

The known receipt context continues to require source activity plus two distinct checkpoints to fit within the receipt row count. Combined activity may include older saved events and is not limited by that batch row count. Origin revision checks apply only when the same source-row or event identity actually occurs; no scope or input group must contain the origin, and UUIDs from different record namespaces are not equated.

Only bounded count/posted/pending metadata crosses pages. A complete traversal must match the selected side's saved counts; early termination, excess rows, duplicate/out-of-order references, invalid continuations and posting-count discrepancies fail closed. Refresh uses progress preceding the displayed page, while next-page navigation uses its completed progress. Zero activity is a valid empty selection; an empty checkpoint is not. The UI does not recompute a financial total across pages or independently certify all six selections. The existing server comparison reconstruction remains authoritative for the saved equation and cross-part reference consistency.

[InputInspection](../frontend/workspace/src/InputInspection.tsx) inherits the protected session, same-origin POST/CSRF, no-store and bounded-response behavior. Loads and failures remove previous rows; navigation, session replacement, lock and sign-out discard them. Generation and unmount guards ignore late responses. Financial values, including zero and historical checkpoints, are masked in text, accessible content and attributes; display currency does not convert native evidence. No browser storage, private provider reference, automatic retry or production fixture fallback is added.

## Verification

[Focused regressions](../frontend/src/test/workspace-inputs.test.tsx) cover the six selections, native values, historical lineage, checkpoint/date/posting rules, known-origin constraints, exact counts and bounded pagination, clear-on-load/error, masking, context replacement and late-response disposal. Existing comparison, receipt, activity, lot and investment checks remain prerequisites.

The focused input suite passes 65 tests. The unchanged comparison, receipt, activity, lot and investment suites pass another 319 checks. TypeScript and both frontend builds pass. Synthetic Chromium checks at 1440px and 390px in both themes cover all six selections, exact cash and twelve-place units, a 25+1 page traversal, refresh/reset behavior, keyboard focus, masked zero values, native display-preference invariance, empty browser storage and sign-out clearing. A malformed scope response clears the view and blocks access. Automated WCAG A/AA checks, including contrast, report no violations, and neither width has horizontal overflow.

| Selection | Desktop light | Desktop dark | Mobile light | Mobile dark |
| --- | --- | --- | --- | --- |
| Opening | [Capture](images/frozen-input-inspection/opening-1440-light.png) | [Capture](images/frozen-input-inspection/opening-1440-dark.png) | [Capture](images/frozen-input-inspection/opening-390-light.png) | [Capture](images/frozen-input-inspection/opening-390-dark.png) |
| Activity | [Capture](images/frozen-input-inspection/activity-1440-light.png) | [Capture](images/frozen-input-inspection/activity-1440-dark.png) | [Capture](images/frozen-input-inspection/activity-390-light.png) | [Capture](images/frozen-input-inspection/activity-390-dark.png) |
| Closing | [Capture](images/frozen-input-inspection/closing-1440-light.png) | [Capture](images/frozen-input-inspection/closing-1440-dark.png) | [Capture](images/frozen-input-inspection/closing-390-light.png) | [Capture](images/frozen-input-inspection/closing-390-dark.png) |

These captures contain synthetic evidence only. No real statement or live provider session is used. Full integration follows the [standard verification groups](verification.md).
