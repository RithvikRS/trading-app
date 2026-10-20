# Step 2: UI prototype proposal

Proposed on 21 October 2026 after PR #2 was merged into `main`. Planning is authorized; implementation is awaiting approval. Approving Step 2A authorizes only the first increment below, including the minimum frontend setup needed to run it. Later increments require their own approval.

## Purpose and scope

Review the application's visual design and everyday interactions before connecting financial accounts. The first deliverable is a polished, responsive Overview using synthetic data. It should answer three questions quickly: what assets are tracked, where they are held, and which data needs attention.

Use the agreed React, TypeScript, and Vite direction. Reuse the prototype's components and design tokens during later application work. Select maintained dependencies and lock exact versions during the approved setup; keep the initial dependency set small. This proposal does not install packages or introduce application code.

The prototype runs on localhost and contains fabricated fixtures only. Backend services, databases, authentication implementation, real statements, provider authorization, live quotes, trade execution, and deployment belong to later approved work. A visible demo label must make the simulated nature of the data clear.

## Visual direction

Propose a calm financial workspace with a graphite dark theme, an equally considered warm-neutral light theme, and restrained teal accents. Follow the system theme initially and provide an explicit light/dark control. Reserve positive, negative, and warning colors for meaning, with text or icons alongside color.

Use a readable sans-serif typeface, aligned tabular numerals, a consistent spacing scale, thin separators, and limited elevation. Give the main total and data freshness clear hierarchy. Prefer compact account rows and useful charts to decorative panels. Fonts, icons, and other assets must be local or bundled with an appropriate license.

Desktop uses a narrow navigation sidebar and a flexible main canvas. Mobile uses a compact header and accessible navigation drawer, with content ordered by importance. Keep the working title neutral until an app name is selected. Motion should be brief and respect reduced-motion preferences.

## Increment sequence

| Increment | Deliverable | Approval boundary |
| --- | --- | --- |
| 2A | Frontend setup, shared visual foundations, responsive shell, and Overview | Proposed first implementation step; stop after its PR and review |
| 2B | Investment holdings, search/filter/sort, and a holding detail panel | Separate approval after Overview review |
| 2C | Bank balances and searchable activity, with sample transfer/category review | Separate approval; simulated changes only |
| 2D | Budget and cash-flow prototype with sample monthly categories and recurring items | Separate approval; no financial persistence |
| 2E | Import-review walkthrough and connection-status screens | Separate approval; bundled sample batches only, no upload or provider login |

Steps 2B-2E describe the intended sequence, not permission to build all screens at once. Their detailed criteria will be refined after the preceding review. The shell may show future destinations with clear planned status, but must not present inactive destinations as working links.

## Step 2A: Overview

| Area | Proposed content and behavior |
| --- | --- |
| Header | Overview title, demo label, INR/USD display choice, hide/show amounts, and theme control |
| Summary | Tracked assets, invested assets, and cash; clear reporting currency and valuation date |
| Value history | A restrained line chart with 1M/3M/6M controls, dated values, keyboard-accessible details, and a tabular alternative |
| Allocation | Asset-class distribution with readable labels, amounts, percentages, and an accessible list |
| Accounts | Sample INDmoney, advisor-held funds, UBS employee shares, HDFC, and SBI summaries with separate holdings/balance and price freshness where relevant |
| Attention | Actionable sample stale-data or incomplete-valuation messages, with a detail disclosure explaining affected coverage |
| Recent activity | A short fabricated activity list, distinguishing purchases, dividends, transfers, and spending; full history follows later |

Use "Tracked assets", rather than "Net worth", because liabilities and full account coverage are not established. Invested assets include the tracked holdings; cash includes the explicitly represented bank and broker cash balances once each. Account totals, allocation, and summary values must agree for the same snapshot.

The value-history chart describes changes in tracked asset value, not investment return. State that deposits, withdrawals, and FX movements can change it. Do not add an unexplained gain percentage, XIRR, tax calculation, or simulated trading control to this increment.

The currency control changes reporting values consistently using an explicitly labeled, dated demo FX rate. Original-currency amounts remain distinguishable. Fixture values use exact decimal strings or minor units, with a documented conversion/rounding approach; do not introduce a production accounting engine. Chart range controls affect the displayed history, not the current summary snapshot.

## Interaction and state coverage

- Theme, reporting currency, privacy mode, chart range, navigation drawer, and account/attention disclosures work with mouse, touch, and keyboard.
- Privacy mode conceals absolute amounts in cards, activity, chart labels, tooltips, and accessible names. It is a visual privacy control, not authentication or encryption.
- A clearly labeled demo-state control selects populated, loading, empty, partial/stale, and failed-load fixtures. These controls do not contact providers or pretend to refresh live accounts.
- Loading uses stable skeletons and does not flash false zero balances. Empty state explains that no sample accounts are present and offers a reset to populated demo data.
- Partial/stale state identifies affected accounts and dates. Unknown values remain unknown; any subtotal excluding unpriced holdings is labeled with its coverage.
- Failed-load state gives a clear explanation and a local simulated retry. Preserve the last valid fixture view where appropriate.
- Focus returns correctly when the navigation drawer or a disclosure closes. No essential information is available only on hover.

Persist only non-sensitive display preferences if needed. Keep fabricated account and activity state in memory or bundled fixtures. Do not add file inputs, credential forms, account-connect actions, analytics, remote fonts, or third-party requests to the running prototype. Bind both local development and preview servers to loopback, without a tunnel or public publishing.

## Acceptance and review evidence

| Area | Evidence required for Step 2A |
| --- | --- |
| Visual quality | Review screenshots at 1440 px desktop, 768 px tablet, and 390 px mobile widths in both themes; consistent typography, alignment, and spacing |
| Responsive behavior | No clipped controls or page-wide horizontal scrolling at 320 px; readable content with enlarged text and a reflow check at 400% browser zoom |
| Accessibility | Semantic landmarks and headings, named controls, visible focus, keyboard completion of all interactions, chart alternatives, and reduced-motion behavior |
| Contrast and targets | At least 4.5:1 contrast for normal text and 3:1 for large text; aim for 44 by 44 CSS px primary touch targets and verify smaller controls against the applicable minimum |
| Financial presentation | Known fixture totals reconcile; currency changes are consistent; transfers do not inflate spending; missing/stale data is labeled; asset-value changes are not labeled as returns |
| Privacy | Hidden amounts do not leak through tooltips or accessible labels; no personal data, secrets, or external runtime requests |
| Behavior | Demonstrate all five fixture states, theme/currency/privacy/range controls, local retry, and drawer focus behavior |
| Engineering | Type checking and production build pass; use targeted tests for fixture reconciliation, currency presentation, privacy behavior, and material state transitions |

Accessibility targets follow the relevant W3C guidance for [text contrast](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html), [target size](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html), and [reflow](https://www.w3.org/WAI/WCAG22/Understanding/reflow.html). These are acceptance targets, not a claim of completed conformance testing. A 44 px touch target is a usability goal; the cited minimum criterion uses 24 CSS px with defined exceptions.

Choose checks according to behavior and risk. Do not add tests that only assert CSS classes or duplicate static markup. Review dependency advisories and licenses before accepting the initial dependency set, and record limitations alongside actual results.

## Delivery and stopping point

After Step 2A approval, build only the Overview increment. Keep the minimum setup and reusable shell within that feature's scope. Record coherent work in conventional commits such as `chore(frontend): initialize prototype tooling` and `feat(ui): add responsive overview prototype` as each part is completed and checked.

Update this proposal's status, the product plan, README run instructions, and relevant development documentation. Commit and push on `dev`, open or update the `dev`-to-`main` PR with screenshots and validation evidence, and wait for review. Merging and implementation of Step 2B need separate approval.

Current status: proposal documented; no frontend scaffolding, dependency installation, UI implementation, or infrastructure changes have begun.
