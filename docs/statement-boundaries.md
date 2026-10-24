# Statement periods and checkpoint boundaries

[Step 4F.3.1](financial-data-plan.md) retains explicit statement meaning needed by [reconciliation](reconciliation-contracts.md). Migration [0014_statement_boundaries](../backend/migrations/versions/0014_statement_boundaries.py) adds a cash date basis to immutable normalized batches and a boundary label to immutable staged checkpoints. It creates no financial movements, balance calculation, completion receipt or endpoint.

## Supplied meaning

A normalized batch may specify `cash_date_basis` as `booking`, `value` or `settlement`. It requires an observation with known period dates and complete or partial activity coverage. Missing basis remains null; the service does not choose booking dates automatically. Unit reconciliation uses trade dates independently.

The basis is part of the normalization version and canonical digest. Correcting its interpretation requires a new normalizer version and the expected current batch revision. Earlier batches remain readable, and their review decisions become superseded. This preserves the original document observation while retaining the parser's interpretation history.

A dated native-cash or selected-position checkpoint may explicitly carry `reconciliation_boundary` as `before_period` or `after_period`. Its date must match the observation's period start or end respectively. Unknown periods, full-account scopes, other row kinds and incompatible dates cannot supply this label. A calendar date or exact timestamp alone never creates a boundary label. Future parsers must obtain this meaning from supported source semantics.

Both Python staging and PostgreSQL enforce these relationships. Metadata is immutable and owner-scoped, and the authentication role gains no access. Snapshot reads retain the metadata through their original staged row and batch. Values, timestamps, dates, source coverage and missing reasons retain their existing contracts.

## Comparing checkpoints

For a one-day statement, a balance before the period and a balance after the period can legitimately differ. Date-only snapshots with these explicit opposite labels describe different points and do not conflict merely because their calendar dates match.

Different values at the same labeled boundary still conflict. Unknown boundary meaning remains ambiguous and cannot bypass a same-day conflict. Equal exact instants still conflict when values differ, regardless of boundary labels. A boundary label neither selects a source nor makes incomplete history complete; existing explicit selection, correction and stale-review rules continue to apply.

## Migration and recovery

New normalized batches use contract **5**. Canonical content for contracts 1–4 excludes the new fields, preserving historical hashes. Existing rows gain null metadata. Runtime writes require contract 5; restoring an older contract cannot attach these new fields. A downgrade is allowed only when no version-5 batch or new metadata exists, so it cannot discard interpretation history.

Recovery format **11** covers the same **36 application tables**: 34 durable tables and two intentionally omitted session/admission tables. The new columns are included in the encrypted manifest. Separate-cluster recovery compares both owners' original metadata, complete durable rows, constraints, grants and policies; previous sessions remain revoked. Old-format objects must be restored with their matching source revision before migrating and exporting the current format.

Tests cover exact replay, changed interpretations, owner isolation, absent periods, invalid scopes/dates, direct-SQL bypass, same-day and exact-instant conflicts, interrupted migration, legacy hash preservation, downgrade refusal and encrypted recovery. All fixtures are fabricated.

Step **4F.3.2** will bind these source declarations to current owned ledger facts, stable idempotency keys and immutable reconciliation receipts in one transaction. This increment does not treat declarations alone as proof that a ledger is complete.
