# HDFC credit-card prototype

Step 9A adds a separate Credit Cards screen to the synthetic prototype at `#/credit-cards`. It uses the existing Indigo & Apricot themes, display currency and privacy controls. No protected application screen or financial record is introduced.

## Walkthrough

One fictional HDFC billing account shows primary and add-on activity sharing a single liability and limit. No card number, issuer identifier, login or upload is present. Last four digits are omitted. The examples illustrate product behavior and do not represent a supported HDFC statement format.

The account overview separates October's source total due from a separately dated outstanding observation. Unbilled and available-credit values were not supplied and stay unknown. Available credit is not calculated as limit minus outstanding and is never counted as cash. There is no utilization chart or monetary geometry.

Statement history contains an October statement with complete supplied rows and a September statement with incomplete activity and unknown opening/minimum values. August and earlier periods are missing, not empty. Statement detail preserves billing-period dates, statement date, due date, closing liability, total due and minimum due independently. Total due and closing liability are never added together. Payment status remains unknown, including for September's passed due date.

October's fabricated opening liability plus posted debits minus posted credits equals its closing liability. This evidence walkthrough excludes later entries and pending authorizations, and filters never change reconciliation. The partial-data state removes one purchase and explicitly withholds the calculation instead of inventing an adjustment.

Activity can be searched by description and filtered by posted/pending status and type. Entry inspection shows the original fabricated narration, amount, transaction/posting dates, source and liability meaning. Payments are settlements, not another purchase expense; refunds are not income; both retain unknown relationships. Two ambiguous instalment labels demonstrate why original purchase, conversion and principal must not be added as separate spending. No spending totals, paid state, bank match, repayment schedule or future interest are inferred.

## Privacy and interaction

All monetary fields, including limits and original-currency values, use the shared display boundary. USD values use the dated synthetic FX rate; original INR values remain explicitly labeled. Original narration remains source text, not a rewritten FX amount.

Hide amounts also hides descriptions and complete narration, disables and clears search, removes its effect on the list, and leaves no financial values in accessible labels or chart geometry. Amount masking works in account, statement, reconciliation and inspection views. Inspection buttons include their visible descriptions in accessible names when shown; masked names contain only a fixture entry label, the hidden-description placeholder and entry type.

Statement and source-inspection controls support keyboard activation, focus on the opened section and focus restoration to the actual opener (or the activity heading if filtering removes an inspected row). Responsive rows retain explicit table roles and headers on narrow screens. Empty, loading, partial/stale and simulated failure states follow the prototype's existing Demo state control. Loading/empty states remove inspection data. The sample never replaces missing protected data.

Searches, selections and inspection state stay in component memory and are cleared on remount. Only the existing display preferences persist. The URL contains only the screen route; no description, amount or source record is stored there.

## Scope and verification

Focused tests cover exact statement arithmetic, pending/later-entry exclusion, unknown versus zero, filters, source meaning, keyboard focus, INR/USD conversion, masking and accessible attributes, loading/error/partial behavior, memory-only selection, unchanged asset totals and structural accessibility. The protected-build module guard explicitly rejects credit-card fixture or UI imports.

Owned credit accounts, durable statements, migrations, uploads, parser support, bank-payment matching, categories and budget/cash-flow integration remain later Step 9 increments in the [credit-card plan](credit-cards-plan.md). Replacement-card history, credit balances/overpayments, partial/grouped payment allocation and imported-source correction review need those contracts and are deliberately outside this fabricated walkthrough. The prototype introduces no API, schema, provider call, account credential or package dependency.


## Visual review

Browser checks use fabricated evidence at 1440px and 390px in both themes, including statement/source inspection, keyboard focus restoration, INR/USD display, masking, demo states, horizontal reflow and WCAG 2.0/2.1 A/AA checks. Desktop and mobile screenshots were visually inspected. These checks do not establish real issuer-format or account compatibility.

| View | Desktop light | Desktop dark | Mobile light | Mobile dark |
| --- | --- | --- | --- | --- |
| Account, statement history and activity | [Light](images/credit-cards-prototype/overview-1440-light.png) | [Dark](images/credit-cards-prototype/overview-1440-dark.png) | [Light](images/credit-cards-prototype/overview-390-light.png) | [Dark](images/credit-cards-prototype/overview-390-dark.png) |
| Statement reconciliation and source inspection | [Light](images/credit-cards-prototype/statement-1440-light.png) | [Dark](images/credit-cards-prototype/statement-1440-dark.png) | [Light](images/credit-cards-prototype/statement-390-light.png) | [Dark](images/credit-cards-prototype/statement-390-dark.png) |
