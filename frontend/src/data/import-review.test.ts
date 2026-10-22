import { describe, expect, it } from 'vitest'
import { getImportBatches, previewImport } from './imports'
import type { ImportBatch, ImportId } from './imports'
import { batchReview, changeImportReview, createImportReviewState, permittedChoices, proposeImport, resetImportReviews, reviewImport, undoImportReview } from './import-review'
import type { ImportOperation, ImportReviewState } from './import-review'
const fixture = (id: ImportId = 'i01') => getImportBatches().find(batch => batch.id === id)!
const apply = (batch: ImportBatch, state: ImportReviewState, operation: ImportOperation) => changeImportReview(state, batch, proposeImport(batch, state, operation))
const suggested = (batch: ImportBatch) => apply(batch, createImportReviewState(), { type: 'suggestions' })

describe('Reversible import review boundary', () => {
  it.each([
    ['i01', [16, 0, 0, 0], true, 0n], ['i02', [0, 16, 0, 0], true, 0n], ['i03', [10, 5, 0, 1], false, -18000n],
    ['i04', [2, 0, 1, 0], false, null], ['i05', [0, 11, 0, 1], false, 0n], ['i06', [0, 0, 0, 7], false, 913410n], ['i07', [11, 0, 0, 0], false, -220000n],
  ] as const)('%s has independently expected suggested counts and combined reconciliation', (id, counts, ready, difference) => {
    const batch = fixture(id), result = reviewImport(batch, suggested(batch))
    expect(Object.values(result.counts)).toEqual(counts)
    expect(result.ready).toBe(ready); expect(result.difference?.minor ?? null).toBe(difference)
  })
  it('requires supplied distinct-identity proof before including an overlap', () => {
    const batch = fixture('i03'), item = previewImport(batch).rows.find(row => row.row.id === 'row-t06')!
    expect(permittedChoices(batch, item)).toEqual(['include', 'exclude'])
    let state = suggested(batch)
    state = apply(batch, state, { type: 'row', rowId: item.row.id, choice: 'include' })
    const result = reviewImport(batch, state)
    expect(result.counts).toEqual({ included: 11, present: 5, excluded: 0, unresolved: 0 })
    expect(result.ready).toBe(true); expect(result.computed?.minor).toBe(18642000n)
    expect(result.proposed.groups.map(group => [group.status, group.credits.minor, group.debits.minor, group.net.minor])).toEqual([['posted', 80000n, 6233590n, -6153590n], ['pending', 0n, 129900n, -129900n]])
    batch.distinctPairs = []
    expect(permittedChoices(batch, item)).toEqual(['exclude'])
    expect(reviewImport(batch, state).counts.unresolved).toBe(16)
    expect(apply(batch, createImportReviewState(), { type: 'row', rowId: item.row.id, choice: 'include' }).history).toHaveLength(0)
  })
  it('counts a repeated occurrence once and requires its canonical choice', () => {
    const batch = fixture('i04'); let state = suggested(batch)
    expect(reviewImport(batch, state).proposed.groups[0]!.debits.minor).toBe(36000n)
    expect(batchReview(state, batch.id).decisions['row-t05-copy']!.matches[0]!.id).toBe('row-t05')
    state = apply(batch, state, { type: 'row', rowId: 'row-t05', choice: 'exclude' })
    expect(reviewImport(batch, state).blockers.join(' ')).toMatch(/canonical/)
  })
  it.each(['i05', 'i06', 'i07'] as const)('excluding every row cannot clear %s financial blockers', id => {
    const batch = fixture(id); let state = createImportReviewState()
    for (const row of batch.rows) state = apply(batch, state, { type: 'row', rowId: row.id, choice: 'exclude' })
    expect(reviewImport(batch, state).counts).toEqual({ included: 0, present: 0, excluded: batch.rows.length, unresolved: 0 })
    expect(reviewImport(batch, state).ready).toBe(false)
    const attempt = apply(batch, state, { type: 'complete' }); expect(attempt.batches).toBe(state.batches); expect(attempt.history).toBe(state.history)
  })
  it('does not let net-zero omissions or omitted pending records establish coverage', () => {
    const batch = fixture(); batch.rows = [batch.rows[0]!, { ...batch.rows[1]!, original: { ...batch.rows[1]!.original, amount: batch.rows[0]!.original.amount } }]
    batch.closing = batch.opening
    let state = createImportReviewState()
    for (const row of batch.rows) state = apply(batch, state, { type: 'row', rowId: row.id, choice: 'exclude' })
    expect(reviewImport(batch, state).difference?.minor).toBe(0n)
    expect(reviewImport(batch, state).blockers.join(' ')).toMatch(/Necessary source records/)
    const normal = fixture(); state = suggested(normal)
    const pending = previewImport(normal).rows.find(row => row.normalized.status === 'pending')!
    state = apply(normal, state, { type: 'row', rowId: pending.row.id, choice: 'exclude' })
    expect(reviewImport(normal, state).difference?.minor).toBe(0n); expect(reviewImport(normal, state).ready).toBe(false)
  })
  it.each(['revision', 'fingerprint', 'mapping', 'amount', 'baseline', 'coverage', 'currency', 'missing row'] as const)('rejects stale %s evidence atomically and retains incompatible decisions', change => {
    const batch = fixture(), initial = suggested(batch), proposal = proposeImport(batch, initial, { type: 'complete' })
    if (change === 'missing row') batch.rows.pop()
    if (change === 'revision') batch.revision = 'r2'
    if (change === 'fingerprint') batch.fingerprint = 'example-r2'
    if (change === 'mapping') batch.account = 'sbi'
    if (change === 'amount') batch.rows[0]!.original.amount = '1.00'
    if (change === 'baseline') batch.baseline.rows.push(batch.rows[0]!)
    if (change === 'coverage') batch.complete = false
    if (change === 'currency') batch.opening = { currency: 'USD', minor: batch.opening!.minor }
    const result = changeImportReview(initial, batch, proposal)
    expect(result.batches).toBe(initial.batches); expect(result.history).toBe(initial.history); expect(result.message).toMatch(/changed/)
    expect(reviewImport(batch, initial).rows.every(row => row.status === 'Needs review · Evidence changed')).toBe(true)
    expect(reviewImport(batch, initial).ready).toBe(false)
  })
  it('rejects changed choices, cross-batch tokens, and stale actions after undo/reset', () => {
    const batch = fixture(), initial = suggested(batch), proposal = proposeImport(batch, initial, { type: 'complete' })
    const modified = apply(batch, initial, { type: 'row', rowId: 'row-t01', choice: 'exclude' })
    for (const state of [modified, undoImportReview(modified), resetImportReviews(initial)]) {
      const result = changeImportReview(state, batch, proposal); expect(result.batches).toBe(state.batches); expect(result.message).toMatch(/changed/)
    }
    expect(changeImportReview(initial, fixture('i02'), proposal).history).toBe(initial.history)
    const changedAction = { ...proposeImport(batch, initial, { type: 'row', rowId: 'row-t01', choice: 'exclude' }), operation: { type: 'row' as const, rowId: 'row-t02', choice: 'exclude' as const } }
    expect(changeImportReview(initial, batch, changedAction).batches).toBe(initial.batches)
  })
  it('rejects invalid choices and unknown row IDs without partial mutation', () => {
    const batch = fixture('i05'), state = createImportReviewState()
    for (const rowId of ['row-t26', '__proto__', 'unknown']) {
      const result = apply(batch, state, { type: 'row', rowId, choice: 'include' })
      expect(result.batches).toBe(state.batches); expect(result.history).toHaveLength(0)
    }
  })
  it('completes idempotently, locks edits until reopen, and invalidates receipts before further decisions', () => {
    const batch = fixture(), state = suggested(batch), completion = proposeImport(batch, state, { type: 'complete' })
    let done = changeImportReview(state, batch, completion)
    expect(done.history).toHaveLength(2); expect(reviewImport(batch, done).receipt?.counts.included).toBe(16)
    expect(changeImportReview(done, batch, completion)).toBe(done)
    expect(apply(batch, done, { type: 'complete' })).toBe(done)
    expect(apply(batch, done, { type: 'row', rowId: 'row-t01', choice: 'exclude' }).batches).toBe(done.batches)
    done = apply(batch, done, { type: 'reopen' }); expect(reviewImport(batch, done).receipt).toBeNull()
    done = apply(batch, done, { type: 'row', rowId: 'row-t01', choice: 'exclude' }); expect(reviewImport(batch, done).ready).toBe(false)
    expect(batchReview(done, batch.id).decisions['row-t01']).toMatchObject({ previous: 'include', choice: 'exclude', original: batch.rows[0] })
    done = undoImportReview(done); expect(reviewImport(batch, done).ready).toBe(true)
    done = undoImportReview(done); expect(reviewImport(batch, done).receipt).toBeTruthy()
  })
  it('makes stale receipts unavailable after a baseline changes', () => {
    const batch = fixture(), state = apply(batch, suggested(batch), { type: 'complete' })
    batch.baseline.id = 'comparison-r2'
    const review = reviewImport(batch, state); expect(review.receipt).toBeNull(); expect(review.ready).toBe(false)
    expect(review.blockers.join(' ')).toMatch(/previous completion/)
  })
  it('sets aside/reopens with decisions retained and restores rows independently of undo', () => {
    const batch = fixture(), state = suggested(batch), aside = apply(batch, state, { type: 'aside' })
    expect(reviewImport(batch, aside).ready).toBe(false)
    expect(apply(batch, aside, { type: 'complete' }).batches).toBe(aside.batches)
    const reopened = apply(batch, aside, { type: 'reopen' }); expect(reviewImport(batch, reopened).ready).toBe(true)
    const restored = apply(batch, reopened, { type: 'row', rowId: 'row-t01', choice: 'restore' })
    expect(reviewImport(batch, restored).counts.unresolved).toBe(1)
    expect(undoImportReview(restored).batches).toBe(reopened.batches)
  })
  it('keeps separate batch choices and one independent import undo/reset history', () => {
    const first = fixture(), second = fixture('i02'), state = suggested(first), next = apply(second, state, { type: 'suggestions' })
    expect(next.batches.i01).toBe(state.batches.i01); expect(undoImportReview(next).batches).toBe(state.batches)
    expect(resetImportReviews(next).batches).toEqual({}); expect(resetImportReviews(next).history).toEqual([])
  })
  it('rejects amount-affecting actions when hidden or unavailable, while undo/reset work', () => {
    const batch = fixture(), state = suggested(batch)
    for (const operation of [{ type: 'complete' }, { type: 'row', rowId: 'row-t01', choice: 'exclude' }] satisfies ImportOperation[]) expect(changeImportReview(state, batch, proposeImport(batch, state, operation), false).batches).toBe(state.batches)
    expect(undoImportReview(state).history).toHaveLength(0); expect(resetImportReviews(state).batches).toEqual({})
  })
  it('rejects ambiguous baseline duplicates and preserves immutable source evidence', () => {
    const batch = fixture('i02'), original = structuredClone(batch), state = suggested(batch)
    apply(batch, state, { type: 'complete' }); expect(batch).toEqual(original)
    batch.baseline.rows.push(structuredClone(batch.baseline.rows[0]!))
    expect(reviewImport(batch, suggested(batch)).blockers.join(' ')).toMatch(/Comparison baseline identity/)
  })
})
