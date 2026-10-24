# Lot evidence and corrections: Step 4D.3

[Lot services](../backend/trading_db/lots.py) persist sourced acquisition and remaining-lot observations. [Event services](../backend/trading_db/events.py) and lot services now append corrections, cancellations and reinstatements while retaining every earlier version. Migration [0010_lots_corrections](../backend/migrations/versions/0010_lots_corrections.py) adds three lot tables, explicit correction state, and backward-compatible normalization metadata. These remain internal persistence primitives; financial routes, file parsing, completion receipts and connected views follow separately.

## Lot identity and evidence scopes

A lot has an opaque identity under an existing account position. Recording a first source row can create that identity; subsequent observations join it only through an explicitly supplied lot ID. Source date, quantity, security name or amount similarity never links lots automatically. Provider lot-reference matching remains part of later import identity work.

| Scope | Supplied evidence | What remains unproven |
| --- | --- | --- |
| Acquisition | Positive original quantity, observation date, optional supplied acquisition date and monetary components | Complete disposal history, remaining quantity and a chosen tax-lot method |
| Remaining lot | Nonnegative remaining quantity at the observation date, optional acquisition date and monetary components | Original acquisition quantity, missing purchases/disposals and complete historical coverage |

The same lot can retain several independent observations, including competing descriptions on the same date. Reads return source-scoped evidence, not an automatically selected or summed lot balance. Each observation has its own correction chain. Acquisition and remaining scopes cannot be changed into one another through a correction. An unknown acquisition date stays null; it is never copied from the observation date or inferred from another observation. A supplied acquisition date cannot follow its observation date.

Quantity, unit price, acquisition cost, discount amount, reported tax basis, fee and withholding retain their independent source strings and exact numeric values. Known acquisition cost, reported basis and discount amount must be nonnegative; unknown values keep their missing reasons. A zero remaining quantity does not prove how or when the lot was disposed of. The standard [value bounds](financial-values.md#values-and-serialization) remain in force.

For ESPP evidence, a supplied purchase cost, monetary discount amount and reported tax basis are distinct facts. No cost/basis is derived from current price, quantity, or a discount assumption. `discount_amount` means a supplied total monetary amount; a percentage-only discount needs a separate supported contract and is not interpreted as money. Components may retain different currencies when those currencies belong to the account; no FX conversion or combination is performed. A supplied unit-price currency must match the mapped listing/fund currency when known.

Recording, correcting or cancelling lot evidence creates no cash or quantity movement. Original purchases require their own supported event evidence. No disposal allocation, taxable gain, cost-basis calculation or investment return is added.

## Versioned corrections

A correction identifies an existing event or lot observation, a fresh currently included source row, the expected current record revision, the expected review revision, and an allowlisted reason. Source, observation, batch and mapping context are rechecked under the shared owner lock. The account must be active. Corrections preserve the event's account/position/instrument/kind, or the lot observation's lot/scope. Reassignment across those identities remains unsupported; conflicting context cannot silently move economics.

| Reason | Supported change |
| --- | --- |
| `source_correction` | Replace the supplied economics/dates of an active record with newly reviewed evidence in the same identity and scope |
| `posting_update` | Event only: pending → posted with unchanged component roles, numeric amounts, currencies, missing-value semantics and trade date; independently supplied settlement/booking/value dates may be added |
| `cancellation` | Withdraw an active event or lot observation using an explicitly reviewed cancellation occurrence with a supplied booking date |
| `reinstatement` | Restore a cancelled record using newly reviewed ordinary event/lot evidence in its original identity and scope |

Cancellation evidence contains no invented zero values or reversed amounts. Its new record version has no components or movements. The previous version, original components and source linkage remain intact. Event account reads include cancellation status for inspection; effective movement reads select only the latest version, so old movements disappear from effective activity without being deleted. Lot observation reads exclude cancelled observations by default, with an explicit inspection option to include them. Pending movements remain separate from posted movements.

All eight supported event kinds can be cancelled and reinstated. A cancellation cannot create a new event or lot, cancel an already cancelled record, or be consumed by both an event and a lot. An actual reversal transaction is separate supplied activity; the service never constructs it by negating the original event. Cancellation is an evidence correction, not a command to a bank, broker or trading venue.

Exact correction replay returns the same historical revision, even if a later revision now exists. Changed expected revisions, target, review revision or reason conflict. Competing corrections serialize and cannot branch; concurrent retries of the same change produce one version. A failure after any component/movement write rolls back the new version and leaves the earlier one effective. History reads are bounded and never rewrite source values or review decisions.

## Ownership and integrity

`lots`, `lot_observations` and `lot_components` use forced active-owner policies, composite owner references, explicit INSERT columns, and no runtime UPDATE/DELETE/TRUNCATE or audit-time assignment. The authentication role cannot access them. Existing event/source policies remain in place. Records, private components and fixed service errors do not disclose financial values through representations or logs.

Database triggers share the Python service's owner lock. Deferred constraints enforce complete source-matching components, supplied dates, position/account/instrument context, immediate predecessor links, valid state/reason transitions and uniqueness of source consumption across event and lot tables. Corrections cannot escape these rules through direct restricted-role SQL. An observation's review decisions are locked after either service consumes it.

Default read pages contain 25 records, with a maximum of 100 and exclusive opaque cursors. Each table remains limited to 1,000 records per owner through these internal services. Financial completion and economic deduplication across distinct sources remain [Step 4F](financial-data-plan.md#review-completion-and-deduplication); a persisted record alone does not attest that an import reconciles or that its history is complete.

## Migration and recovery

Normalization contract **3** includes the optional acquisition date and admits the new lot discount/cancellation semantics. Contracts 1 and 2 retain their original canonical content and digests, excluding the new date field. Existing rows gain no inferred acquisition date, discount or basis. Legacy event versions remain active initial records with no correction reason. Step 4D.3 introduced version-3 batches; [Step 4E.1](snapshot-evidence.md#migration-and-recovery) now creates version 4 with optional snapshot metadata. Contracts 1–3 retain their hashes; new metadata cannot be smuggled into a legacy contract, including during restore.

The new migration preserves existing version-1/version-2 evidence and recorded events. Tests exercise interrupted upgrade rollback, repeated application and disposable downgrade/re-upgrade with legacy records. Downgrade refuses once version-3 evidence, lots or financial correction versions exist. Shared migrations remain unchanged, and normal development migration seeds no owners or financial records.

Recovery format **13** enumerates all **40 application tables**: 38 durable and the two deliberately omitted session/admission tables. The separate-cluster drill restores corrected, cancelled and reinstated events, acquisition/remaining lot histories, distinct purchase/discount/basis evidence, and unknown later basis while preserving the earlier reported value. It compares every durable row and database constraints/grants/policies, then checks that effective reads count only current movements. Identifier keys are recovered separately and prior browser sessions remain revoked.

Formats 1–8 require restoration with their matching release/schema followed by tested forward migrations. The current reader never relabels old objects. Production-volume backup, hosted Supabase verification, provider lot semantics and representative export compatibility remain outside this bounded local exercise.

Verification includes independent contract cases, all supported event cancellation kinds, pending/posted separation, exact and conflicting concurrent retries, interrupted writes, direct-SQL constraint/ownership/grant denials, cross-table source reuse prevention, legacy digest preservation and encrypted recovery. Actual check results are recorded in the PR. [Step 4E.1](snapshot-evidence.md) adds snapshots and selection; [Step 4E.2](market-evidence.md) adds market evidence, followed by [Step 4F.1](event-evidence.md) for provider identity reuse.

[Step 4G.2a](event-lot-reads.md) exposes lot identities, current observations and retained revision history through bounded authenticated queries. Acquisition and remaining scopes, supplied cost/discount and missing reported basis remain separate; responses do not infer tax lots or sum observations.
