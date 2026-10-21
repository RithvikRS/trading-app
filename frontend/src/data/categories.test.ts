import { describe, expect, it } from 'vitest'
import { bankReconciliation, bankScope, bankTotals, defaultBankingFilters, getBankSnapshots, getBankTransactions, sampleRefund, sampleTransfer } from './banking'
import { categoryOptions, categoryRestriction, categorySuggestion, classifiedSpending, previewCategories, refundEvidence } from './categories'
import type { CategoryTarget } from './categories'
import { changeTransfers, createTransferState, effectiveClassification, pairId, transferReviewStatus } from './transfers'
import type { TransferState } from './transfers'
import { getActivity, getPositions, getSummary, spendingTotal } from './portfolio'
import { money } from './money'

const records = getBankTransactions()
const item = (id: string) => records.find(record => record.id === id)!
const initial = () => createTransferState()
const apply = (state: TransferState, ids: string[], target: CategoryTarget) => changeTransfers(state, { type: 'categorize', preview: previewCategories(ids, target, records, state) }, records)
const totals = (state = initial(), scope = records, all = records) => classifiedSpending(scope, all, state, record => effectiveClassification(record, all, state))

describe('category decisions and shared review history', () => {
  it('keeps suggestions separate from effective source classifications until explicitly accepted', () => {
    expect(categorySuggestion(item('t13'), initial())?.category).toBe('shopping')
    expect(effectiveClassification(item('t13'), records, initial()).category).toBe('unresolved')
    const state = apply(initial(), ['t13'], 'suggested')
    expect(effectiveClassification(item('t13'), records, state)).toEqual({ category: 'shopping', provenance: 'suggestion' })
    expect(transferReviewStatus(item('t13'), records, state)).toBe('reviewed')
    expect(item('t13').sourceCategory).toBe('unresolved')
    expect(categorySuggestion(item('t13'), state)).toBeNull()
    expect(categorySuggestion(item('t13'), apply(state, ['t13'], 'dining'))).toBeNull()
  })
  it.each(['salary', 'interest', 'other-income'] as const)('rejects income category %s for a debit', category => {
    expect(previewCategories(['t13'], category, records, initial()).edits).toEqual([])
    expect(categoryOptions(item('t13'))).not.toContain(category)
  })
  it.each(['groceries', 'dining', 'fee', 'other-expense', 'transfer', 'refund', 'investment'] as const)('rejects category %s for an unresolved credit', category => {
    expect(previewCategories(['t20'], category, records, initial()).edits).toEqual([])
  })
  it('explains protected roles and preserves pending, transfer, refund, and investment entries', () => {
    const preview = previewCategories(['t16', 't15', 't25', 't08', 't09', 'missing', 't11'], 'other-expense', records, initial())
    expect(preview.edits.map(edit => edit.id)).toEqual(['t11'])
    expect(preview.excluded).toHaveLength(6)
    expect(preview.excluded.every(entry => entry.reason.length > 0)).toBe(true)
    const changed = changeTransfers(initial(), { type: 'categorize', preview }, records)
    expect(Object.keys(changed.classifications)).toEqual(['t11'])
    expect(changed.pairs).toEqual(initial().pairs)
    expect(categoryRestriction({ ...item('t13'), ownerId: 'someone-else' }, initial())).toBeTruthy()
    expect(categoryRestriction({ ...item('t13'), amount: money('0') }, initial())).toBeTruthy()
  })
  it('previews mixed selections and applies only the explicitly listed eligible changes atomically', () => {
    const preview = previewCategories(['t05', 't06', 't20', 't05'], 'health', records, initial())
    expect(preview.ids).toEqual(['t05', 't06', 't20'])
    expect(preview.edits.map(edit => [edit.from.category, edit.after.category])).toEqual([['dining', 'health'], ['dining', 'health']])
    expect(preview.excluded.map(entry => entry.id)).toEqual(['t20'])
    const state = changeTransfers(initial(), { type: 'categorize', preview }, records)
    expect(state.history).toHaveLength(1)
    expect(effectiveClassification(item('t05'), records, state).category).toBe('health')
    expect(effectiveClassification(item('t06'), records, state).category).toBe('health')
    expect(changeTransfers(state, { type: 'undo' }, records).classifications).toEqual({})
    const repeated = changeTransfers(state, { type: 'categorize', preview }, records)
    expect(repeated.classifications).toEqual(state.classifications)
    expect(repeated.history).toHaveLength(1)
    expect(previewCategories(['t05', 't06'], 'health', records, state).edits).toEqual([])
  })
  it('rejects the whole stale preview when a source, classification, or transfer membership changes', () => {
    const preview = previewCategories(['t10', 't13'], 'groceries', records, initial())
    const changed = apply(initial(), ['t13'], 'health')
    const stale = changeTransfers(changed, { type: 'categorize', preview }, records)
    expect(stale.error).toBe(true); expect(stale.classifications).toEqual(changed.classifications)
    const missing = changeTransfers(initial(), { type: 'categorize', preview }, records.filter(record => record.id !== 't13'))
    expect(missing.error).toBe(true); expect(missing.classifications).toEqual({})
    const modified = records.map(record => record.id === 't13' ? { ...record, amount: money('3501') } : record)
    expect(changeTransfers(initial(), { type: 'categorize', preview }, modified).error).toBe(true)
    const paired = changeTransfers(initial(), { type: 'confirm', pair: { id: pairId('t10', 't20'), debitId: 't10', creditId: 't20' } }, records)
    expect(changeTransfers(paired, { type: 'categorize', preview }, records).error).toBe(true)
    expect(changeTransfers(paired, { type: 'categorize', preview }, records).classifications).toEqual({})
  })
  it('clears a reviewed category to unresolved and undo restores its prior provenance', () => {
    const accepted = apply(initial(), ['t13'], 'suggested')
    const cleared = apply(accepted, ['t13'], 'unresolved')
    expect(effectiveClassification(item('t13'), records, cleared)).toEqual({ category: 'unresolved', provenance: 'manual' })
    expect(transferReviewStatus(item('t13'), records, cleared)).toBe('needs-review')
    expect(categorySuggestion(item('t13'), cleared)).toBeNull()
    expect(changeTransfers(cleared, { type: 'undo' }, records).classifications).toEqual(accepted.classifications)
  })
  it('shares undo with transfer review and preserves a previous manual category beneath a pair', () => {
    const classified = apply(initial(), ['t10'], 'groceries')
    const paired = changeTransfers(classified, { type: 'confirm', pair: { id: pairId('t10', 't20'), debitId: 't10', creditId: 't20' } }, records)
    const unpaired = changeTransfers(paired, { type: 'undo' }, records)
    expect(effectiveClassification(item('t10'), records, unpaired).category).toBe('groceries')
    expect(changeTransfers(unpaired, { type: 'undo' }, records).classifications).toEqual({})
    const unlinked = changeTransfers(initial(), { type: 'unlink', pair: sampleTransfer }, records)
    expect(previewCategories(['t15'], 'groceries', records, unlinked).edits).toHaveLength(1)
  })
  it('never partially undoes a batch when one source is missing and resets all decisions', () => {
    const state = apply(initial(), ['t05', 't06'], 'health')
    const undone = changeTransfers(state, { type: 'undo' }, records.filter(record => record.id !== 't06'))
    expect(undone.error).toBe(true); expect(undone.classifications).toEqual(state.classifications)
    expect(changeTransfers(state, { type: 'reset' }, records).classifications).toEqual({})
    expect(changeTransfers(state, { type: 'reset' }, records).history).toEqual([])
  })
})

describe('classified spending and verified refund attribution', () => {
  it('distinguishes gross expenses, verified refunds, net spending and unresolved coverage exactly', () => {
    expect(totals()).toEqual({ gross: money('36764.90'), refunds: money('800'), net: money('35964.90'), outgoing: money('16500'), incoming: money('18000'), unresolved: 6 })
    expect(totals(apply(initial(), ['t13'], 'suggested')).net).toEqual(money('39464.90'))
    expect(totals(initial(), getBankTransactions(true), getBankTransactions(true)).net).toEqual(money('33764.90'))
  })
  it('keeps a refund as a credit and follows purchase corrections, clear and undo without double counting', () => {
    const state = apply(initial(), [sampleRefund.purchaseId], 'health')
    expect(refundEvidence(item('t08'), records, state)?.category).toBe('health')
    expect(effectiveClassification(item('t08'), records, state).category).toBe('refund')
    expect(totals(state).net).toEqual(totals().net)
    const cleared = apply(state, ['t07'], 'unresolved')
    expect(refundEvidence(item('t08'), records, cleared)).toBeNull()
    expect(effectiveClassification(item('t08'), records, cleared).category).toBe('unresolved')
    expect(totals(cleared)).toEqual({ gross: money('33564.90'), refunds: money('0'), net: money('33564.90'), outgoing: money('19700'), incoming: money('18800'), unresolved: 8 })
    expect(totals(changeTransfers(cleared, { type: 'undo' }, records))).toEqual(totals(state))
  })
  it('books verified refunds in their own period while resolving purchase evidence outside filters', () => {
    const scope = bankScope(records, { ...defaultBankingFilters, from: '2026-10-08', to: '2026-10-08' })
    expect(totals(initial(), scope).gross).toEqual(money('0'))
    expect(totals(initial(), scope).net).toEqual(money('-800'))
    expect(totals(initial(), [item('t07')]).net).toEqual(money('3200'))
  })
  it('does not count orphaned, excess, cross-currency or unverified refunds as income or an offset', () => {
    const noPurchase = records.filter(record => record.id !== 't07')
    expect(totals(initial(), noPurchase, noPurchase).refunds).toEqual(money('0'))
    expect(refundEvidence({ ...item('t08'), amount: money('3200.01') }, records, initial())).toBeNull()
    expect(refundEvidence({ ...item('t08'), amount: money('800', 'USD') }, records, initial())).toBeNull()
    expect(refundEvidence({ ...item('t08'), id: 'unverified' }, records, initial())).toBeNull()
    expect(refundEvidence({ ...item('t08'), ownerId: 'another-owner' }, records, initial())).toBeNull()
  })
  it('preserves original records, balances, reconciliation and assets while updating the Overview excerpt', () => {
    const before = bankTotals(records), reconciled = getBankSnapshots().map(snapshot => bankReconciliation(snapshot, records))
    const state = apply(initial(), ['t14'], 'health')
    expect(getActivity(false, state).find(entry => entry.id === 't14')?.detail).toBe('HDFC Bank · Health')
    const cleared = apply(state, ['t14'], 'unresolved')
    expect(spendingTotal(getActivity(false, cleared))).toEqual(money('0'))
    expect(getBankTransactions()).toEqual(records)
    expect(bankTotals(getBankTransactions())).toEqual(before)
    expect(getBankSnapshots().map(snapshot => bankReconciliation(snapshot, records))).toEqual(reconciled)
    expect(getSummary(getPositions()).total).toEqual(money('5086080'))
  })
})
