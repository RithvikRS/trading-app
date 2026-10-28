# Selected bank cash evidence: Step 8C.1

Protected Banking opens one saved cash choice for a selected HDFC or SBI account and declared native currency. A usable selected resolution supplies its exact reported cash and source date. This view does not calculate a current or available bank balance, total partial pages, convert currency, select evidence or connect to a bank.

## Chosen scope and resolution

The account directory provides an explicit **View saved cash** action. The owner chooses INR or USD from that account's declared currencies and requests the saved choice. Selection discovery validates the entire bounded account page before filtering: another declared native currency is valid, while a position, undeclared currency, duplicate chain or duplicate native scope is inconsistent for a bank account. No matching choice means no saved choice was found; it does not mean zero cash or no retained reports.

The protected resolver determines whether a saved choice is selected, explicitly cleared, stale, cancelled, archived or conflicting. Only a selected result can supply the main amount. A stale choice describes a changed pinned revision or source-review context, not the calendar age of a report. An archived account can still resolve as cleared or stale under the existing resolver precedence; the view preserves that state and separately identifies the archived account. No calendar freshness threshold is invented.

All displayed values remain exact source decimal strings in the selected native currency, including negative cash, zero and negative zero. The global INR/USD display preference does not convert native evidence. Amount masking covers main and historical financial values in visible and accessible content. An absent selection, a cleared choice and a cancelled revision are distinct from a saved zero.

## Retained choices and exact snapshot revisions

Choice history shows immutable selection revisions and their original pinned snapshot identities. Opening a pin requests that exact revision first, using an exclusive revision cursor. A separate action opens the latest retained snapshot page. These are different reads: a later correction or cancellation must not silently replace the pinned revision. Earlier pages are contiguous, descending and bounded to 25 records; at most 100 pages can be traversed in one inspection.

The inspector labels active historical amounts as retained evidence, including when the main choice is stale or archived. Cancelled revisions have no amount and do not record zero. Returning to the selected view resolves again instead of restoring a prior usable amount. Returning to choice history rereads its original page. There are no choice, correction or selection writes in this slice.

The original clicked choice and pinned snapshot remain distinct from the highest observed revision. Selection-chain and snapshot-root anchors have separate monotonic floors. Changing a choice from one snapshot root to another does not transfer the old root's revision floor. Repeated equal-head revisions must preserve their exact immutable facts; current flags and current account lifecycle remain contextual. A previously observed archived account cannot later appear active in a fresh response within the same inspection. Previously validated comparison anchors keep their original lifecycle metadata when archival is learned; refresh and exact-pin return validate new rows against the learned archived state without retroactively invalidating those anchors. At most 100 snapshot-root anchors are retained in component memory.

## Source facts and validation

Every response is validated completely inside the authenticated finance projection before display. Cash revisions require the selected owned account, declared native currency and null position/instrument. Active revisions have one known native `net_cash` component and a source date. Original source timestamps and decimal spelling are preserved. Legal active scopes are `native_cash`, `full_account` and absent; a supplied reconciliation boundary requires native-cash scope and a date. Cancellation retains an optional source date and mandatory booking date, empty components, and no instant, scope or boundary.

Expandable provenance shows only returned fields: snapshot revision, source, observation, batch, source row, source-review revision, reported period, coverage, date basis and boundary. Scope and coverage do not establish complete account history. The view adds no mapping revision, acquisition time, statement membership or other inferred lineage. Catalogue browsing, source-history traversal and import receipt expansion remain separate work.

## Privacy and recovery

Loads clear displayed evidence immediately. Component-generation checks discard both valid and malformed late payloads after navigation before their financial projection is evaluated; the shared client retains its authentication and transport boundary. Lock, sign-out and replacement sessions clear protected content. An unavailable nested read drops the account and inspection context; explicit retry starts from a fresh bank directory. Protocol inconsistencies fail closed.

The view uses existing same-origin, MFA/session-bound, CSRF-protected read routes. It stores no financial content, tokens or navigation history in browser storage and adds no backend, schema, recovery, dependency or provider changes. Indigo and Apricot styling follows both existing themes, labelled native selectors, keyboard focus, expandable technical references and compact mobile cards.

## Verification

The final focused run passed all 257 tests. The affected run passed all 943 cases across 14 protected frontend suites, including the focused cases. Final TypeScript and both production builds passed. The first focused attempt retained 255 passes and two failures: broad amount-prefix sentinels also matched the intentionally preserved timestamp fraction `.123456`. The corrected full-HTML checks use complete original/formatted monetary values and additionally assert that source timestamps remain intact. No product behavior, deadline, worker isolation or intended privacy assertion was relaxed. Earlier static typing attempts and their corrections remain recorded.

Synthetic Chromium passed 29 scenarios and 102 accessibility/layout/privacy checks at 1440px, 390px and 320px, in light and dark modes. These exercise explicit native choices, every resolver state, retained-history pagination, exact pins versus latest pages, equal-head drift and revision regression, different snapshot roots, learned archival, nested recovery, large exact USD values, negative zero, masking and preference changes. Four malformed late-response scenarios confirm disposal after navigation; lock, sign-out and changed sessions clear cash content. Keyboard/disclosure checks, visible controls at least 44px high, preview security headers and protected CSRF/context requests passed. Automated WCAG A/AA and contrast checks found no violations, no horizontal overflow was observed and browser storage remained empty.

All 12 captures were visually inspected. Interaction checks use a 1000px-high viewport; only capture height expands to contain the full bank section, without product CSS changes. Selected views measure 774/1003/1119px at desktop/mobile/narrow widths; the three-revision history measures 1387/1889/2175px. Source timestamps reflow intact, and technical details stay expandable. The owned browser and preview were stopped, with port 8043 verified closed.

Logs retain the existing jsdom canvas notices and demo chunk-size warning. This is synthetic local verification; live provider, hosted authentication, deployment and the final integrated repository gate are separate checks. No provider connection or private financial record was used.

| Width | Selected light | Selected dark | History light | History dark |
| --- | --- | --- | --- | --- |
| 1440px | [Capture](images/selected-bank-cash/selected-1440-light.png) | [Capture](images/selected-bank-cash/selected-1440-dark.png) | [Capture](images/selected-bank-cash/history-1440-light.png) | [Capture](images/selected-bank-cash/history-1440-dark.png) |
| 390px | [Capture](images/selected-bank-cash/selected-390-light.png) | [Capture](images/selected-bank-cash/selected-390-dark.png) | [Capture](images/selected-bank-cash/history-390-light.png) | [Capture](images/selected-bank-cash/history-390-dark.png) |
| 320px | [Capture](images/selected-bank-cash/selected-320-light.png) | [Capture](images/selected-bank-cash/selected-320-dark.png) | [Capture](images/selected-bank-cash/history-320-light.png) | [Capture](images/selected-bank-cash/history-320-dark.png) |
