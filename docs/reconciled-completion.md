# Reconciled import completion

Step **4F.3.2c** extends [atomic completion](completion-receipts.md) to complete-activity statements. A `reconciled` request commits only when every supplied native cash or position scope has balanced source and combined-ledger equations. Its financial effects, explicit selections, receipt, exact compared inputs and rule version commit together. Failure rolls everything back.

This is an internal persistence service. It adds no financial HTTP mutation, upload parser, provider connection or connected screen. The protected workspace remains empty until its data flow is implemented.

## What a balanced receipt establishes

The receipt establishes exact arithmetic for the statement's declared period and native scopes. Each scope uses an explicit source opening checkpoint to anchor that period, the applicable activity, and an explicit closing checkpoint. Source and combined absolute checkpoints must agree. This does not attest continuity with earlier history, independently authenticate a provider document, calculate returns or reconcile tax basis.

The owner-state digest remains an anti-staleness token. Current owner access, source/review/mapping revisions, target revisions and conflict checks are independently enforced under the common owner transaction lock. The caller supplies no amounts, totals, coverage assertions or verified-baseline flags.

| Scope | Identity | Activity date | Included value |
| --- | --- | --- | --- |
| Cash | Canonical account and INR or USD | Explicit statement booking, value or settlement basis | `net_cash` only |
| Units | Canonical account position | Trade date | Signed quantity movement |

Currencies and positions remain separate. Gross amounts, fees and withholding are retained evidence; adding them again to net cash would count the same economics twice. Unknown fee/withholding components block the affected cash equation. Missing unit prices, acquisition cost or reported tax basis do not become zero or a fabricated cash movement. Lot observations can accompany a statement but do not themselves establish a ledger equation or a complete lot history.

## Source and combined inputs

The **source** side includes every applicable supplied occurrence. Every required native scope needs exactly one `before_period` and one `after_period` checkpoint on its period endpoints. Missing, duplicate or unknown boundaries block completion. Full-account snapshots cannot stand in for native checkpoints. Exclusions, unsupported rows and amount-free cancellation candidates cannot produce a full reconciled receipt. Complete coverage cannot fall back to `limited` mode.

The **combined** side includes every effective active owned event in the native scope and period after the proposed effects. Current event roots count once; corrections replace the effective revision, while immutable history remains. Proven provider/raw occurrence identity can reuse an existing event. Equal-looking payments without identity remain separate. Known activity outside the period is outside the equation; missing posted dates remain unresolved and block completion rather than being filtered out.

Pending activity is retained and counted separately, with no contribution to posted totals. Known source activity dates outside the declared period are rejected, including pending dates. A zero-activity equation is valid only with explicit known equal checkpoints; absence of a balance never becomes zero.

Combined checkpoints reference the exact recorded or corrected opening/closing snapshots. Current, active, unconflicting evidence is required. Competing amounts on the same checkpoint date with unknown or equal boundary meaning block full reconciliation, including mixed date/instant precision. Opposite explicit boundaries remain distinct, subject to existing exact-instant conflict rules. These period anchors do not silently replace the user's selected balance; selection stays an explicit request.

## Immutable evidence and database enforcement

[Migration 0017](../backend/migrations/versions/0017_reconciled_completion.py) adds `completion_scopes` and `completion_inputs`. Scope records retain the native identity, period/date basis, rule version, exact checkpoints, independent source/combined posted totals and posted/pending counts. Inputs retain original decimal strings, exact numeric values, dates, posting state and owner-composite references to staged review rows or historical event/snapshot revisions.

Python evaluates both equations through the [exact reconciliation contracts](reconciliation-contracts.md). PostgreSQL independently verifies source membership, native scopes, checkpoint identity, historical economics, counts, sums and current combined membership. Symmetric set checks reject omitted inputs even when opposite signed omissions would leave a balanced sum. Deferred constraints catch an extra event or correction inserted later in the same transaction.

All queries are bounded and values are exact decimals. Native cash retains at most two fractional digits, units at most twelve; arithmetic does not perform FX conversion or rounding. The existing 1,000-record admission limits also apply to comparison tables. A comparison that exceeds its input budget fails as a whole rather than truncating evidence. Runtime receives narrow select/insert grants, forced active-owner RLS and no update/delete privilege; the authentication role has no access.

Exact retries return the original receipt and comparisons before checking live state. Later source replacements, corrections, selections and reference-key rotation cannot rewrite what the earlier receipt compared. New receipts must pass current-state checks; historical restoration validates immutable facts without demanding that old event revisions remain current.

## Migration, recovery and verification

The current head is `0017_reconciled_completion`. Existing limited receipts remain readable with no comparison scopes. Earlier shared migrations are unchanged. Empty comparison tables can be downgraded to the prior schema; persisted reconciliation evidence prevents downgrade. Development uses forward migration.

Recovery format **13** covers **40 application tables**, with 38 durable tables and two intentionally omitted session/admission tables. The encrypted two-owner drill retains limited and full receipts, exact comparison inputs, subsequent event/checkpoint corrections, selected balances and rotated private provider references. It compares all durable rows, constraints, grants and policies, replays historical requests using recovered keys, and keeps old sessions revoked. Older recovery objects require their matching release/schema before forward migration and re-export.

Focused verification covers cash and fractional units, separate currencies, date bases, known zero activity, pending counts, unknown components, source/combined mismatch, provider overlap, legitimate repeated payments, checkpoint ambiguity, direct SQL tampering and omitted scopes/offsetting inputs. It also covers concurrent replay, late transaction changes, owner/role denial, immutable grants, bounded input admission, migration rollback and encrypted recovery. Hosted Supabase verification remains outstanding. Protected financial read APIs follow in **4G**.
