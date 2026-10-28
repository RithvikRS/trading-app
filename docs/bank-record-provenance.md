# Saved bank record provenance: Step 8A.2

Protected Banking can trace a saved event revision to its source records and batch completion effects. The entry works from latest and historical records, including archived accounts, without an investment position. It uses only existing protected reads and introduces no provider connection, parser or financial write.

## Source records

Source records retain the clicked revision's source and observation identity, coverage and supplied period. The view is source-wide: other records can describe other accounts or periods. Current/replaced flags may change as new evidence arrives; current does not mean fresh or complete. Coverage claims, overlapping periods and predecessor links do not establish reconciliation or complete bank history.

Pages contain at most 25 observations in UUID order. Every row binds to the selected source, and a row matching the known observation must preserve its exact coverage and dates. A complete traversal must include that originating observation. Only page metadata and an origin-seen flag survive pagination; prior payloads are discarded. Refresh uses preceding-page metadata, first-page navigation resets it, and the 100-page cap explicitly leaves the view incomplete.

## Saved receipt effects

Batch receipts preserve historical completion metadata and all effects in the batch, including other accounts, positions and snapshots. The originating row is identified only when source-row identity, review revision, event identity and saved record revision agree. Record, link, correction and exclusion outcomes stay distinct; a link is not an additional movement and an exclusion has no financial target.

The shared receipt reader has explicit full and row-effects navigation modes. Banking uses row-effects mode with a required parent reset callback. Its metadata describes retained reconciliation without offering comparison or input navigation. Existing investment and lot callers retain full comparison/input navigation and their current retry behavior. The restricted snapshot-mutation receipt validator is unchanged.

Receipt pages bind to the exact clicked batch and coverage. Empty pages remain valid and do not imply zero activity. Effect pages retain exact row/selection totals, origin inclusion and bounded count-only traversal, including refresh and reset. A whole batch is never silently filtered to the selected bank account; effect rows do not contain account or currency fields that could justify such an inference.

## Navigation, privacy and failures

The clicked origin and the return destination are separate. A historical origin keeps its own source and record revisions. [Step 8A.4](bank-frozen-inputs.md) retains a separate highest-seen history revision through source, receipt, comparison and input navigation, preserving the original clicked identity. Returning to history rejects a head below that floor. Back navigation refetches and validates records instead of restoring stale amounts.

Loading removes prior amounts. Unavailable provenance reads, including nested receipt/effect refreshes, remove account and origin context and return to the generic Banking failure state. Explicit retry starts with a fresh account-directory read. Protocol mismatches fail closed through the existing authenticated response boundary. Generation/unmount and session-context checks discard late navigation, lock, sign-out and replacement-session responses.

Values retain original native precision and existing masking. The new source/receipt views display metadata and effects, not calculated balances. Technical references and detailed scope explanations are expandable; record states and origin labels remain visible. There is no storage, URL-based private state, raw statement exposure, automatic retry, category/transfer inference or completeness claim.

## Verification

Acceptance cases cover immutable source metadata, current/replaced observations, source-wide and whole-batch behavior, origin inclusion and page caps, historical return floors, missing receipts, exact effect identities/counts, bank-only receipt navigation, nested failure reset, full-mode compatibility and privacy/session behavior. Fresh verification on unchanged source passed all 64 provenance tests. A seven-suite compatibility run passed 444 of 454 cases; ten existing receipt, comparison and lot cases reached their unchanged 5-second test timeout. All ten passed in one subsequent isolated diagnostic. The failed combined run remains failed: these results do not establish a passing combined 454-case run or a root-cause fix. The final integrated local gate remains required.

TypeScript and both frontend builds passed. Fresh synthetic Chromium checks passed at 1440 px and 390 px in both themes, with zero WCAG/contrast findings or horizontal overflow. They checked keyboard focus and expanded disclosures, native masking, source/effect 25+1 paging and refresh/reset, immutable-origin rejection, unavailable source/receipt/effect recovery through a fresh account directory, historical return floors, archived accounts, complete-coverage receipt metadata without comparison actions, empty browser storage and sign-out clearing. Twelve fresh captures were visually inspected. The preview process was stopped and its port closed. The representative synthetic captures below remain valid for the unchanged presentation. No live provider, private statement or source-format compatibility was exercised.


Synthetic captures:

| View | Desktop light | Desktop dark | Mobile light | Mobile dark |
| --- | --- | --- | --- | --- |
| Source records | [1440 light](images/bank-record-provenance/sources-1440-light.png) | [1440 dark](images/bank-record-provenance/sources-1440-dark.png) | [390 light](images/bank-record-provenance/sources-390-light.png) | [390 dark](images/bank-record-provenance/sources-390-dark.png) |
| Import completion | [1440 light](images/bank-record-provenance/receipts-1440-light.png) | [1440 dark](images/bank-record-provenance/receipts-1440-dark.png) | [390 light](images/bank-record-provenance/receipts-390-light.png) | [390 dark](images/bank-record-provenance/receipts-390-dark.png) |
| Historical row effects | [1440 light](images/bank-record-provenance/effects-1440-light.png) | [1440 dark](images/bank-record-provenance/effects-1440-dark.png) | [390 light](images/bank-record-provenance/effects-390-light.png) | [390 dark](images/bank-record-provenance/effects-390-dark.png) |
