# Source and combined-state reconciliation

[Step 4F.2](financial-data-plan.md) implements [pure reconciliation contracts](../backend/trading_api/reconciliation.py) for supplied native cash or position evidence. They calculate exact, conditional results over bounded typed inputs. Step 4F.3 will resolve these inputs from owned database records, verify current review/mapping/baseline state inside the transaction, and persist completion receipts.

## Scope and boundaries

A cash scope identifies one canonical account and its INR or USD currency. A unit scope identifies one account and one position. Every checkpoint and activity carries the same explicit scope; mixing accounts, currencies or positions fails validation. No FX conversion, prices, portfolio returns, tax basis or inferred settlement amounts enter the equation.

Periods are inclusive calendar-date ranges with an explicit date basis. Cash uses booking, value or settlement dates; units use trade dates. Calendar dates retain their original precision. A checkpoint must explicitly describe the balance before the period or after the period, with its date matching the corresponding period boundary. A date-only snapshot does not establish that boundary meaning by itself. Timestamp inputs and ambiguous date formats are rejected.

Opening and closing checkpoints retain opaque source references, revisions, exact source strings and missing reasons. Activities retain their own references/revisions, original values, supplied dates and posted/pending state. References cannot occur twice within one view. Source and combined views can refer to shared evidence when its identity is established. At most 1,000 activities are accepted per view.

The caller must establish ownership, authentic provenance, the meaning of source boundary labels, complete period coverage, the selected date basis and current economic versions. The pure contracts do not access a database or provider. In particular, `baseline_verified`, coverage and unresolved/excluded counts must be derived from database evidence during completion; future routes must not trust these assertions from a browser payload.

## Exact equation and outcomes

For each view, calculate **opening + posted native movements = reported closing**. Negative movements retain their supplied signs. Pending activity remains in the evidence and count but contributes no posted amount; a missing pending amount remains null. No fee estimate, quantity-times-price calculation or rounding fills a gap.

| Outcome | Meaning |
| --- | --- |
| `balanced` | Complete declared activity, explicit compatible checkpoints and all required known posted values produce the supplied closing amount exactly. |
| `mismatch` | The known, compatible equation produces a different closing amount. `difference` is calculated closing minus reported closing. |
| `unavailable` | Coverage, baseline, boundaries, dates, required values, exclusions or unresolved components prevent a reconciliation claim. Derived totals remain null. |
| `not_applicable` | Snapshot-only evidence has no activity equation. It does not attest complete history. |

Partial/unknown coverage stays unavailable even when supplied numbers happen to match. A missing opening, closing or posted amount never becomes zero. Known complete coverage with zero activities can legitimately reconcile equal known checkpoints; an empty collection alone cannot establish completeness. Long-position checkpoints must be nonnegative; unit movements and native cash retain their supported signs.

Source reconciliation includes all supplied activity independently of review exclusions. The combined view declares the proposed effective state, a verified baseline and any excluded source activity. Exclusions or unresolved components block a balanced result even when remaining numbers coincide. A posted row outside the period or without a supplied date remains unavailable instead of being silently dropped.

Each view uses the existing explicit 96-digit decimal context with inexact/rounded operations trapped. Individual values keep the established finite range and cash/unit scales. A derived sum may exceed an individual record's magnitude; with 1,000 activities and two checkpoints, the calculation remains below the explicit derived bound of 10^22. Derived amounts serialize as plain decimal strings, without coercion back into the smaller individual-value contract.

## Comparing the views

`reconcile_pair()` requires one source view and one combined view with identical scope, calendar period and date basis. It retains each result independently. Both must balance and their known opening/closing checkpoints must agree numerically for the pair's `balanced` flag to be true. Two internally balanced equations with different absolute balances produce `checkpoint_conflict`; different source formats such as `100.00` versus `100.0` remain numerically equivalent.

Results preserve the complete typed input evidence, finite reason codes, posted/pending counts, exact compared outputs and rule version **1**. Values and dates are hidden from object representations and validation diagnostics. Constructed or copied models are revalidated directly, including nested objects, before serialization or calculation. No warning-based serialization of invalid financial values is used.

## Verification and integration

[Independent tests](../backend/tests/test_reconciliation.py) cover INR/USD cash equations, fractional units, pending and missing values, hostile decimal contexts, zero activity, large bounded sums, mixed identities/currencies, duplicate evidence, incompatible dates, missing coverage/baseline evidence, exclusions, disagreement between independently balanced views and exact JSON output. Fixtures are fabricated.

Step 4F.2 added no migration or dependency. [Step 4F.3.1](statement-boundaries.md) subsequently retains explicit source boundaries and cash date basis; the current database is `0016_completion_receipts` with recovery format 12 covering 38 tables. No financial route or connected screen is added. Step 4F.3.2b implements limited-coverage receipts. Step 4F.3.2c must bind these conditional calculations to validated source/baseline records before completing full activity statements as reconciled. Persisted receipts must preserve compared values, rule versions and source links in the same atomic transaction as their financial effects.
