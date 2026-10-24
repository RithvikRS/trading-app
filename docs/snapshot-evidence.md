# Snapshot evidence and selection: Step 4E.1

[Snapshot services](../backend/trading_db/snapshots.py) persist source-linked position and native-cash checkpoints. They preserve exact components and separate source descriptions without creating trades or cash movements. Migration [0011_snapshots](../backend/migrations/versions/0011_snapshots.py) adds `snapshot_records`, `snapshot_components` and `snapshot_selections`. These are internal services; financial HTTP routes, import completion and connected views remain separate increments.

## Evidence and scope

A position snapshot requires an explicit owned account position, a known nonnegative quantity and a supplied observation date. A cash snapshot requires a known native amount and account currency. Explicit zero is evidence; absent quantity/cash cannot become zero. Optional unit price, purchase cost and reported basis remain independent supplied components, including their missing reasons. No valuation or balance is calculated here.

Records retain their source occurrence, exact review revision, source account, observation period and coverage. Several sources may describe the same canonical position. Recording another description does not add its quantity to any other snapshot. The source's declared scope is preserved:

| Scope | Meaning |
| --- | --- |
| `selected_position` | Evidence describes the explicitly identified position |
| `native_cash` | Evidence describes this account's cash in one currency |
| `full_account` | The source declares account-wide snapshot scope; an individual persisted row does not certify complete membership |
| Unknown | No scope was supplied; it remains null |

Account-wide completion and reconciliation remain Step 4F. A full-account label never turns omitted positions into zero or replaces other selected records automatically. Event-history coverage is separate from snapshot scope. Snapshot-only evidence establishes neither complete transactions nor tax basis. Short positions and unsupported instruments remain outside the current contracts.

## Dates and exact instants

Date-only evidence retains its calendar date and has no invented midnight timestamp. An optional instant must include seconds and an explicit known UTC offset, with up to six fractional digits. Its source-local date must match the supplied snapshot date. The original string preserves the offset and fractional precision; unknown offsets, ambiguous local times, invalid clocks and out-of-range UTC values are rejected in Python and PostgreSQL.

For example, `2026-10-25T00:30:00.120+05:30` and `2026-10-24T19:00:00.120Z` identify the same instant. A date-only observation on either day is not treated as that instant. Dates, source coverage and source revisions remain available to downstream read models; this increment introduces no freshness threshold or scheduled refresh.

## Explicit source selection

An append-only selection chain identifies one snapshot revision for an owned position, or for one account/native-currency pair. Selection requires the expected selection and snapshot revisions, an active account, current included review/mapping/evidence context and an active latest snapshot version. No snapshot is selected automatically on recording.

Comparable active descriptions with different quantities or cash amounts block selection. Comparable means the same date when both are date-only, or the same normalized instant when both carry exact times. Equal values with different decimal spelling do not conflict and are never summed. Date-only versus instant evidence remains noncomparable. Different observation points remain separate checkpoints; explicitly choosing one does not establish a complete ledger balance.

Selecting a preferred source cannot conceal a conflicting immutable quantity. Correct or cancel the conflicting evidence first. A conflict introduced after a selection makes its resolved value unavailable. Changes to source/mapping context also make selection stale; account archival makes it unavailable. Resolution returns a state and exposes a selected snapshot only when those conditions still hold.

Selections can be explicitly cleared, preserving the earlier choices. Reasons are allowlisted (`reviewed`, `newer_evidence`, `correction`, `clear`). Expected revisions, composite constraints and the shared owner lock prevent competing selection branches. Exact retries return the same historical choice without changing current selection.

## Corrections and integrity

Fresh reviewed evidence can append a source correction, cancellation or reinstatement to an existing snapshot. Account, position/instrument, kind and cash currency remain fixed. Every earlier version and original component string survives. Cancellation uses explicit cancellation evidence and creates no reversal amount or financial movement.

A corrected snapshot makes a selection of its earlier revision stale until explicitly reselected. It never silently replaces the selected version. Changing scope or timestamp requires new normalized source evidence. Identity reassignment remains unsupported. History and account reads retain cancelled records for inspection.

All three tables use forced active-owner policies, composite owner references, narrow INSERT grants and no runtime UPDATE/DELETE/TRUNCATE or audit-time assignment. The authentication role has no access. Deferred constraints enforce source-matching components, dates, identity, revision transitions and selection targets. Shared owner locks cover direct restricted-role SQL, service writes and multi-query selection resolution, preventing mixed-version results during concurrent corrections. A source occurrence cannot be consumed by multiple event, lot or snapshot records, and consumed reviews cannot be reopened.

Default pages contain 25 records, with a maximum of 100 and bounded exclusive cursors. Services retain the foundation limit of 1,000 rows per table per owner. These limits are development safety bounds, not production capacity measurements. No raw documents, provider credentials or private external identifiers are added.

## Migration and recovery

New normalization contract **4** includes optional snapshot scope and instant fields. Contracts 1–3 retain their canonical content and digests; legacy rows gain null metadata rather than inferred precision or scope. Legacy contract rows cannot contain the new fields, including during restore. Existing reviewed snapshots can be recorded with their actual older evidence and unknown metadata.

The migration preserves existing accounts, events and lots, supports interrupted-upgrade rollback and repeated application, and refuses disposable downgrade once contract-4 evidence or snapshot/selection records exist. Earlier shared migration files remain unchanged. The disposable downgrade runner exclusively locks forced-policy tables, temporarily allows the schema owner to inspect their rows for safety guards, and restores forced policies before commit. A failed guard rolls the entire transaction back. Ordinary development and hosted databases cannot use that destructive runner path.

Recovery format **13** enumerates **40 application tables**: 38 durable tables and the two deliberately omitted session/admission tables. The separate-cluster drill restores exact snapshot components, equivalent-instant descriptions, correction/cancellation/reinstatement chains, cleared selections, current choices and earlier source coverage alongside existing event/lot histories. It compares durable rows, constraints, grants and policies and verifies effective reads. Identifier keys remain separate and former sessions stay revoked.

Formats 1–8 require their matching release/schema for restoration followed by tested forward migrations. Hosted Supabase compatibility, real export semantics and production-volume backups remain separate. Local development migrations seed no owners or financial records.

Synthetic verification covers precision and invalid timestamps, legacy digests, migration interruption/downgrade safety, source conflicts, unchanged and competing concurrent choices, stale selection after corrections, direct-SQL bypass attempts, partial-write rollback, ownership/role denial and encrypted recovery. Actual local and CI results are recorded in the PR. [Step 4E.2](market-evidence.md) adds quote/NAV and FX evidence; [Step 4F.1](event-evidence.md) adds scoped event evidence reuse.

[Step 4F.3.1](statement-boundaries.md) retains explicit checkpoint boundary labels through source rows. Opposite before/after labels distinguish date-only opening and closing balances on one-day statements. Unknown/same-boundary values and equal exact instants retain conflict checks; labels alone do not select a snapshot or prove a complete ledger.
