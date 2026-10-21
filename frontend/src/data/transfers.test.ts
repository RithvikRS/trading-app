import { describe, expect, it } from 'vitest'
import { bankReconciliation, bankTotals, getBankSnapshots, getBankTransactions, sampleTransfer, selectBankTransactions, defaultBankingControls } from './banking'
import type { BankTransaction } from './banking'
import { changeTransfers, confirmedPairs, createTransferState, effectiveClassification, eligiblePair, pairId, transferCoverage, transferQueue, transferReviewStatus } from './transfers'
import { getActivity, getPositions, getSummary, spendingTotal } from './portfolio'
import { money } from './money'

const records = getBankTransactions()
const record = (id: string) => records.find(item => item.id === id)!
const pair = (debitId = 't10', creditId = 't20') => ({ id: pairId(debitId, creditId), debitId, creditId })
const initial = () => createTransferState()

describe('transfer eligibility and review queues', () => {
  it('finds unique, competing and unmatched cases without automatic confirmation', () => {
    const queue = transferQueue(records, initial())
    expect(queue.suggested).toEqual([pair()])
    expect(queue.ambiguous).toEqual([pair('t12', 't21'), pair('t12', 't22')])
    expect(queue.unmatched.map(item => item.id)).toEqual(['t13'])
    expect(queue.confirmed).toEqual([sampleTransfer])
    expect(queue.dismissed).toEqual([])
    expect(transferCoverage(records, initial())).toEqual({ confirmed: 1, transferred: money('25000'), unresolved: 6, debits: money('16500'), credits: money('18000') })
  })
  it.each([
    { accountId: 'hdfc' }, { ownerId: 'another-owner' }, { status: 'pending' }, { direction: 'debit' },
    { amount: money('8000', 'USD') }, { amount: money('8000.01') }, { amount: money('0') },
    { sourceCategory: 'salary' }, { sourceCategory: 'refund' }, { sourceCategory: 'investment' }, { sourceCategory: 'fee' },
    { date: '2026-10-14' }, { date: '2026-02-31' }, { date: 'invalid' }, { id: 't10' },
  ] as Partial<BankTransaction>[])('rejects an ineligible counterpart %#', change => {
    expect(eligiblePair(record('t10'), { ...record('t20'), ...change })).toBe(false)
  })
  it('uses exact calendar days across month boundaries and ignores narration as evidence', () => {
    const debit = { ...record('t10'), date: '2026-10-31' }
    expect(eligiblePair(debit, { ...record('t20'), date: '2026-11-03', narration: 'unrelated' })).toBe(true)
    expect(eligiblePair(debit, { ...record('t20'), date: '2026-11-04' })).toBe(false)
    expect(eligiblePair(debit, { ...record('t20'), date: '2026-10-28' })).toBe(true)
  })
  it('marks every edge ambiguous when either the credit or debit has multiple counterparts', () => {
    const extra = { ...record('t10'), id: 'extra' }
    const queue = transferQueue([...records, extra], initial())
    expect(queue.suggested).toHaveLength(0)
    expect(queue.ambiguous).toHaveLength(4)
  })
  it('keeps matching independent of activity filters, sorting, reporting currency and source labels', () => {
    const filtered = selectBankTransactions(records, { ...defaultBankingControls, filters: { ...defaultBankingControls.filters, account: 'hdfc', query: '8000' } })
    expect(filtered).toHaveLength(0)
    expect(transferQueue(records, initial()).suggested).toEqual([pair()])
    expect(record('t10').sourceCategory).toBe('unresolved')
  })
})

describe('atomic, reversible transfer decisions', () => {
  it('confirms both legs once, excludes both from unresolved coverage and preserves ledger totals', () => {
    const before = bankTotals(records), snapshots = getBankSnapshots().map(snapshot => bankReconciliation(snapshot, records))
    const state = changeTransfers(initial(), { type: 'confirm', pair: pair() }, records)
    for (const id of ['t10', 't20']) expect(effectiveClassification(record(id), records, state)).toEqual({ category: 'transfer', provenance: 'transfer' })
    expect(transferCoverage(records, state)).toEqual({ confirmed: 2, transferred: money('33000'), unresolved: 4, debits: money('8500'), credits: money('10000') })
    const again = changeTransfers(state, { type: 'confirm', pair: pair() }, records)
    expect(again.pairs).toEqual(state.pairs); expect(again.history).toHaveLength(1)
    expect(bankTotals(getBankTransactions())).toEqual(before)
    expect(getBankSnapshots().map(snapshot => bankReconciliation(snapshot, getBankTransactions()))).toEqual(snapshots)
    expect(getSummary(getPositions()).total).toEqual(money('5086080'))
    expect(effectiveClassification(record('t11'), records, state).category).toBe('fee')
  })
  it('requires an explicit competing pair and rejects stale reuse without a partial update', () => {
    const state = changeTransfers(initial(), { type: 'confirm', pair: pair('t12', 't22') }, records)
    const rejected = changeTransfers(state, { type: 'confirm', pair: pair('t12', 't21') }, records)
    expect(rejected.error).toBe(true); expect(rejected.pairs).toEqual(state.pairs); expect(rejected.history).toEqual(state.history)
    expect(transferQueue(records, state).unmatched.map(item => item.id)).toEqual(['t13', 't21'])
    expect(effectiveClassification(record('t21'), records, state).category).toBe('unresolved')
  })
  it('dismisses only one pair, restores it, and makes both actions idempotent and undoable', () => {
    const target = pair('t12', 't21')
    const dismissed = changeTransfers(initial(), { type: 'dismiss', pair: target }, records)
    expect(transferQueue(records, dismissed).suggested).toContainEqual(pair('t12', 't22'))
    expect(transferQueue(records, dismissed).dismissed).toEqual([target])
    expect(changeTransfers(dismissed, { type: 'confirm', pair: target }, records).error).toBe(true)
    expect(changeTransfers(dismissed, { type: 'dismiss', pair: target }, records).history).toHaveLength(1)
    const restored = changeTransfers(dismissed, { type: 'restore', pair: target }, records)
    expect(transferQueue(records, restored).ambiguous).toHaveLength(2)
    expect(changeTransfers(restored, { type: 'restore', pair: target }, records).history).toHaveLength(2)
    const undoRestore = changeTransfers(restored, { type: 'undo' }, records)
    expect(undoRestore.dismissed).toEqual([target])
    expect(changeTransfers(undoRestore, { type: 'undo' }, records).dismissed).toEqual([])
  })
  it('restores previous classifications, including manual decisions, on unlink and undo', () => {
    const underlying = { ...initial(), classifications: { t10: { category: 'groceries' as const, provenance: 'manual' as const } } }
    const confirmed = changeTransfers(underlying, { type: 'confirm', pair: pair() }, records)
    const unlinked = changeTransfers(confirmed, { type: 'unlink', pair: pair() }, records)
    expect(effectiveClassification(record('t10'), records, unlinked)).toEqual(underlying.classifications.t10)
    expect(transferReviewStatus(record('t20'), records, unlinked)).toBe('needs-review')
    expect(changeTransfers(unlinked, { type: 'unlink', pair: pair() }, records).history).toHaveLength(2)
    const undoUnlink = changeTransfers(unlinked, { type: 'undo' }, records)
    expect(confirmedPairs(records, undoUnlink)).toContainEqual(pair())
    const undoConfirm = changeTransfers(undoUnlink, { type: 'undo' }, records)
    expect(effectiveClassification(record('t10'), records, undoConfirm)).toEqual(underlying.classifications.t10)
    expect(undoConfirm.history).toHaveLength(0)
  })
  it('treats a missing-leg pair as unresolved and reserves the remaining leg until unlink', () => {
    const state = changeTransfers(initial(), { type: 'confirm', pair: pair() }, records)
    const incomplete = records.filter(item => item.id !== 't20')
    expect(transferQueue(incomplete, state).incomplete).toEqual([pair()])
    expect(changeTransfers(state, { type: 'confirm', pair: pair() }, incomplete).error).toBe(true)
    expect(effectiveClassification(record('t10'), incomplete, state)).toEqual({ category: 'unresolved', provenance: 'incomplete' })
    expect(transferCoverage(incomplete, state).transferred).toEqual(money('25000'))
    expect(transferQueue(incomplete, state).unmatched.map(item => item.id)).not.toContain('t10')
    expect(transferQueue(incomplete, changeTransfers(state, { type: 'unlink', pair: pair() }, incomplete)).unmatched.map(item => item.id)).toContain('t10')
    expect(confirmedPairs(records, state)).toContainEqual(pair())
  })
  it('undoes the latest applicable action without recreating an orphaned or conflicting pair', () => {
    let state = changeTransfers(initial(), { type: 'dismiss', pair: pair() }, records)
    state = changeTransfers(state, { type: 'unlink', pair: sampleTransfer }, records)
    const incomplete = records.filter(item => item.id !== sampleTransfer.creditId)
    const undone = changeTransfers(state, { type: 'undo' }, incomplete)
    expect(undone.pairs).toEqual([]); expect(undone.dismissed).toEqual([])
    expect(undone.history.map(item => item.kind)).toEqual(['unlink'])
    expect(changeTransfers(undone, { type: 'undo' }, incomplete).error).toBe(true)
  })
  it('resets decisions and history without creating pairs with missing source records', () => {
    const changed = changeTransfers(initial(), { type: 'confirm', pair: pair() }, records)
    const reset = changeTransfers(changed, { type: 'reset' }, records)
    expect(reset.pairs).toEqual(initial().pairs); expect(reset.history).toEqual([])
    expect(changeTransfers(changed, { type: 'reset' }, []).pairs).toEqual([])
    expect(changeTransfers(changed, { type: 'reset' }, records.filter(item => item.id !== 't25')).pairs).toEqual([])
    expect(getBankTransactions()).toEqual(records)
  })
  it('updates Overview classification on unlink and does not treat unreviewed transfers as spending', () => {
    const state = changeTransfers(initial(), { type: 'unlink', pair: sampleTransfer }, records)
    expect(getActivity(false, state).find(item => item.id === 't15')?.kind).toBe('unresolved')
    expect(getActivity(false, state).find(item => item.id === 't15')?.detail).not.toContain('Confirmed')
    expect(spendingTotal(getActivity(false, state))).toEqual(money('2450'))
    expect(getActivity(false, changeTransfers(state, { type: 'undo' }, records)).find(item => item.id === 't15')?.kind).toBe('transfer')
  })
})
