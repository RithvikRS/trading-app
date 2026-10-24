# Atomic import completion receipts

Step **4F.3.2b** adds internal completion for reviewed **partial activity, unknown coverage, and snapshots**. Events, lot observations, snapshot selections and the immutable receipt commit in one database transaction. A failed row, stale review, changed mapping or conflicting target rolls the operation back.

Complete-activity statements require the [reconciled completion path in 4F.3.2c](reconciled-completion.md). They cannot use limited mode. A limited receipt records the evidence used and the decisions made; it makes no claim that balances or history are complete. It contains no invented zero totals or calculated returns.

## Request and transaction boundary

The [completion service](../backend/trading_db/completion.py) uses the strict [request contracts](completion-preflight.md) and an independently authenticated owner transaction. Requests must cover every staged occurrence exactly once, identify its current review revision, and specify recording, correction or exclusion. Current batch, observation, account/instrument mappings and target revisions are checked against owned database evidence. Exclusions require an excluded review and create no financial effect.

The receipt root is inserted before financial effects. A PostgreSQL trigger compares the supplied baseline with current owner state under the common transaction lock. The baseline now includes receipt identities. Deferred constraints require complete row membership, matching source/target economics, requested selections and current review context before commit. They also catch changes made later in the same transaction, such as replacing the source batch or advancing a selected snapshot.

Callers must finish the transaction before exposing a result. Corrections that advance a newly completed target belong in a subsequent committed transaction. There is no provider or network I/O under the owner lock and no financial write endpoint in this increment.

## Identity, overlap and retries

Each owner has a unique completion key and one receipt per batch. An exact retry returns the original receipt before checking live state, including after later corrections or source replacement. A different request under the same key, or another key for the completed batch, conflicts. Provider references are compared against their protected stored identity separately from the public manifest; matching public bytes alone cannot prove an exact private retry.

| Situation | Result |
| --- | --- |
| Same immutable observation and occurrence under a newer normalizer, with matching current event economics | Link the new evidence to the existing event |
| Same supported provider identity and matching current economics in another observation | Reuse the event and retain the corroborating evidence link |
| Different observations with equal-looking payments and no provider identity | Preserve separate events |
| Changed economics for a consumed occurrence | Require an explicit target, prior revision and correction reason |
| Changed provider reference for an already consumed raw occurrence | Reject; do not create another event to attach the reference |
| Repeated lot or snapshot occurrence under a newer normalizer | Require an explicit correction, even if values match |

Raw identity is proven from immutable financial records or provider evidence links. Receipt links cannot prove each other in a circle. Snapshot/lot reuse is conservative because their original source may have been superseded. A remaining-lot observation can name an earlier acquisition occurrence in the same batch; both must resolve to the same owned position and lot. Missing tax basis remains unknown.

An existing event without a protected provider identity cannot acquire a new reference through completion. It can be adopted without that reference; retroactive identity binding needs a separate workflow.

## Retained decisions

Each receipt row retains its review revision and exact event, lot observation or snapshot revision. Its outcome is deterministic from that relationship:

- **Recorded:** this occurrence is the primary source of revision 1. An existing primitive write can be adopted without claiming it was inserted again.
- **Linked:** another primary source supplies the same proven event identity and economics.
- **Corrected:** this occurrence supplies the explicitly named next revision and reason.
- **Excluded:** no financial target, provider identity or snapshot selection is attached.

Selections are explicit and retain their own snapshot and selection revisions. A newly completed receipt cannot attest an old selection that has already been replaced. Earlier receipts continue to retain their historical choices after later corrections.

Completed occurrences cannot be re-reviewed or posted again through another financial primitive. An exclusion in a new normalization does not reverse an earlier posted event; cancellation or correction requires explicit evidence. An old excluded interpretation can remain in history while a separately normalized occurrence is reviewed anew.

## Database and security

Migration [0016_completion_receipts](../backend/migrations/versions/0016_completion_receipts.py) adds `completion_receipts` and `completion_rows`. Both have forced active-owner row policies, composite owner foreign keys, insert-only runtime grants, bounded admission and no authentication-role access. Runtime updates and deletion are denied. The private provider reference never enters a receipt, canonical request or unkeyed reference digest.

SQL validates the bounded canonical manifest, exact row membership, private-reference presence, target family/revision, source economics, correction reason and selection relationship. Malformed or noncanonical manifests fail before effects. The root checks its byte bound before parsing JSON. The common lock and a volatile baseline read prevent an INSERT that waited for another writer from accepting an earlier statement snapshot.

Receipts and dispositions retain the existing 1,000-record owner/table bound. Nothing is silently truncated to fit. Internal list reads default to 25 and cap at 100; ownership never comes from a request body.

## Recovery and verification

Recovery format **13** covers **40 application tables**: 38 durable tables and two intentionally omitted session/admission tables. The encrypted two-owner drill restores completed exclusions, protected provider identities, original receipts, later event/snapshot corrections and selection history. It compares all durable rows and database permissions, verifies baseline equality across rotation/restore, and replays original requests using separately recovered keys. Previous sessions remain revoked.

Populated receipts prevent downgrade. Disposable tests verify empty downgrade/re-upgrade and complete rollback of an interrupted migration. Development uses forward migrations; older recovery objects require their matching source revision before a tested forward migration.

Tests cover concurrency, exact and conflicting retries, source overlap, legitimate repeated payments, explicit corrections, selection/lot dependencies, late failure rollback, direct SQL tampering, stale context after root insertion, inactive/foreign owners, role denial and immutable grants. Hosted Supabase behavior remains unverified. [Full reconciliation receipts](reconciled-completion.md) extend this boundary. Uploads/parsers, browser review mutations and connected screens remain separate increments.
