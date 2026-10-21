import { describe, expect, it } from 'vitest'
import { bankReconciliation, getBankSnapshots, getBankTransactions } from './banking'
import { budgetOverview, budgetStatus, changeBudgets, createBudgetState, monthlyBudgetActuals, parseBudgetLimit } from './budgets'
import { classifiedSpending, previewCategories } from './categories'
import { changeTransfers, createTransferState, effectiveClassification, pairId } from './transfers'
import { getPositions, getSummary } from './portfolio'

const records = getBankTransactions()
const initial = () => createBudgetState()
const review = () => createTransferState()
const overview = (state = initial(), decisions = review(), source = records, partial = false) => budgetOverview(state, source, decisions, partial)

describe('monthly budget limits and actuals', () => {
  it.each([['0', 0n], [' 1234.5 ', 123450n], ['999999999.99', 99999999999n], ['0001.20', 120n]])('parses %s into exact paise', (input, expected) => {
    expect(parseBudgetLimit(input as string).minor).toBe(expected)
  })
  it.each(['', ' ', '-1', '1,000', '1e3', 'Infinity', 'NaN', '1.001', '.5', '1.', '1000000000', '+4', '<img>', '9'.repeat(10000)])('rejects invalid budget input without coercion: %s', input => {
    expect(parseBudgetLimit(input).error).toBeTruthy()
    const state = changeBudgets(initial(), { type: 'set', category: 'health', decimal: input })
    expect(state.limits).toEqual(initial().limits); expect(state.history).toEqual([])
  })
  it('distinguishes unset and zero, ignores unchanged saves, and reverses set/remove in order', () => {
    let state = initial()
    expect(state.limits.health).toBe(0n); expect(state.limits.fee).toBeUndefined()
    state = changeBudgets(state, { type: 'set', category: 'fee', decimal: '0' })
    state = changeBudgets(state, { type: 'set', category: 'fee', decimal: '0.00' })
    expect(state.history).toHaveLength(1)
    state = changeBudgets(state, { type: 'remove', category: 'fee' })
    expect(state.limits.fee).toBeUndefined()
    state = changeBudgets(state, { type: 'undo' }); expect(state.limits.fee).toBe(0n)
    state = changeBudgets(state, { type: 'undo' }); expect(state.limits.fee).toBeUndefined()
    expect(state.history).toHaveLength(0)
    expect(changeBudgets(state, { type: 'remove', category: 'fee' }).history).toHaveLength(0)
  })
  it('rejects non-expense categories, unsupported owner/month scopes, and stale undo', () => {
    for (const category of ['salary', 'investment', 'refund', 'transfer', 'unresolved'] as const) expect(changeBudgets(initial(), { type: 'set', category, decimal: '1' }).limits).toEqual(initial().limits)
    for (const state of [{ ...initial(), ownerId: 'other-owner' }, { ...initial(), month: '2026-09' }]) {
      expect(changeBudgets(state, { type: 'set', category: 'health', decimal: '50' }).history).toEqual([])
      expect(overview(state).count).toBe(0)
    }
    const state = changeBudgets(initial(), { type: 'set', category: 'health', decimal: '50' })
    const stale = { ...state, limits: { ...state.limits, health: 100n } }
    expect(changeBudgets(stale, { type: 'undo' }).limits.health).toBe(100n)
  })
  it('reconciles category totals to shared classification, preserving the source ledger and asset baseline', () => {
    const before = structuredClone(records), balances = getBankSnapshots().map(s => bankReconciliation(s, records))
    const values = overview()
    expect(values.count).toBe(8); expect(values.planned.minor).toBe(3819900n)
    expect(values.spent.minor).toBe(3595900n); expect(values.remaining.minor).toBe(224000n)
    expect(values.unbudgeted.minor).toBe(590n); expect(values.total.minor).toBe(3596490n)
    expect(values.spent.minor + values.unbudgeted.minor).toBe(values.total.minor)
    const shared = classifiedSpending(records, records, review(), item => effectiveClassification(item, records, review()))
    expect(values.total).toEqual(shared.net)
    expect(values.rows[0]?.category).toBe('utilities'); expect(values.rows[1]?.category).toBe('health')
    expect(values.rows.find(row => row.category === 'housing')?.remaining?.minor).toBe(0n)
    expect(values.outgoing.minor).toBe(1650000n); expect(values.incoming.minor).toBe(1800000n); expect(values.pending).toBe(2)
    expect(values.provisional).toBe(true)
    expect(records).toEqual(before); expect(getBankSnapshots().map(s => bankReconciliation(s, records))).toEqual(balances)
    expect(getSummary(getPositions()).total.minor).toBe(508608000n)
  })
  it('updates actuals/refund attribution after review, clearing and undo, independently of limits', () => {
    let decisions = changeTransfers(review(), { type: 'categorize', preview: previewCategories(['t07'], 'health', records, review()) }, records)
    let values = overview(initial(), decisions)
    expect(values.rows.find(row => row.category === 'shopping')?.net.minor).toBe(0n)
    expect(values.rows.find(row => row.category === 'health')?.net.minor).toBe(400000n)
    expect(values.total.minor).toBe(3596490n)
    decisions = changeTransfers(decisions, { type: 'categorize', preview: previewCategories(['t07'], 'unresolved', records, decisions) }, records)
    values = overview(initial(), decisions)
    expect(values.total.minor).toBe(3356490n)
    expect(values.incoming.minor).toBe(1880000n)
    decisions = changeTransfers(decisions, { type: 'undo' }, records)
    expect(overview(initial(), decisions).total.minor).toBe(3596490n)
    expect(initial().limits.health).toBe(0n)
  })
  it('uses full refund evidence outside the booking period and preserves a net refund', () => {
    const source = records.map(item => item.id === 't07' ? { ...item, date: '2026-09-30' } : item)
    const shopping = overview(initial(), review(), source).rows.find(row => row.category === 'shopping')!
    expect(shopping.net.minor).toBe(-80000n); expect(shopping.remaining?.minor).toBe(380000n)
    expect(shopping.records.map(item => item.id)).toEqual(['t08'])
    expect(budgetStatus(shopping.net.minor, shopping.limit?.minor, true)).toBe('Net refund')
    expect(overview(initial(), review(), source.filter(item => item.id !== 't07')).rows.find(row => row.category === 'shopping')?.net.minor).toBe(0n)
  })
  it('keeps transfer decisions out of expenses and exposes source/classification gaps', () => {
    const pair = { id: pairId('t10', 't20'), debitId: 't10', creditId: 't20' }
    const confirmed = changeTransfers(review(), { type: 'confirm', pair }, records)
    expect(overview(initial(), confirmed).outgoing.minor).toBe(850000n)
    expect(overview(initial(), confirmed).total.minor).toBe(overview().total.minor)
    const partial = overview(initial(), confirmed, getBankTransactions(true), true)
    expect(partial.total.minor).toBe(3376490n); expect(partial.provisional).toBe(true)
    const onlyKnown = records.filter(item => !['t10', 't12', 't13', 't20', 't21', 't22'].includes(item.id))
    expect(overview(initial(), review(), onlyKnown).provisional).toBe(false)
    expect(overview(initial(), review(), onlyKnown, true).provisional).toBe(true)
  })
  it('handles no budgets, foreign records and records outside the cutoff without changing the month scope', () => {
    const values = overview(createBudgetState(false))
    expect(values.count).toBe(0); expect(values.spent.minor).toBe(0n); expect(values.unbudgeted).toEqual(values.total)
    const extra = [ { ...records[1]!, id: 'elsewhere', ownerId: 'another' }, { ...records[1]!, id: 'future', date: '2026-10-21' } ]
    expect(monthlyBudgetActuals([...records, ...extra], review()).total).toEqual(values.total)
    expect(changeBudgets(changeBudgets(initial(), { type: 'remove', category: 'housing' }), { type: 'reset' }).limits).toEqual(initial().limits)
  })
})
