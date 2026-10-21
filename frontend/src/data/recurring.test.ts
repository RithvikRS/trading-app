import { describe, expect, it } from 'vitest'
import { bankReconciliation, getBankSnapshots, getBankTransactions } from './banking'
import type { BankTransaction } from './banking'
import { budgetOverview, createBudgetState } from './budgets'
import { bankCoverage, cashFlow } from './cashFlow'
import type { CashMonth } from './cashFlow'
import { previewCategories } from './categories'
import { money } from './money'
import { getPositions, getSummary } from './portfolio'
import { changeRecurring, createRecurringState, recurringDate, recurringEvidence, recurringOverview, recurringPatterns, recurringSourceKey } from './recurring'
import type { RecurringPattern, RecurringState } from './recurring'
import { changeTransfers, createTransferState } from './transfers'

const records = getBankTransactions(false, null), review = createTransferState()
const pattern = (id: string) => recurringPatterns.find(item => item.id === id)!
const evidence = (id: string, source = records, decisions = review) => recurringEvidence(pattern(id), source, decisions)
const overview = (state = createRecurringState(), source = records, decisions = review, month: CashMonth = '2026-10', partial = false) => recurringOverview(source, decisions, state, month, bankCoverage(partial))!
function decide(state: RecurringState, id: string, type: 'confirm' | 'dismiss' | 'restore' = 'confirm') { return changeRecurring(state, { type, id, evidence: evidence(id).key }, records, review) }
function fromIds(ids: string[]): RecurringPattern {
  const first = records.find(item => item.id === ids[0])!
  return { ...pattern('rent'), id: 'test', accountId: first.accountId, payee: first.counterparty, occurrences: ids.map(id => {
    const item = records.find(item => item.id === id)!
    return { id, source: recurringSourceKey(item), month: item.date.slice(0, 7) }
  }), related: [] }
}

describe('recurring evidence and independent decisions', () => {
  it('starts with seven unconfirmed patterns and no expected money; never auto-confirms', () => {
    const result = overview()
    expect(result.rows).toHaveLength(7); expect(result.reviewed).toBe(0); expect(result.expected).toEqual([])
    expect(result.fixed.minor).toBe(0n); expect(result.needsReview).toBe(1)
    expect(evidence('rent').valid).toBe(true); expect(evidence('rent').min).toBe(2200000n)
    expect(evidence('electricity').min).toBe(170000n); expect(evidence('electricity').max).toBe(190000n)
  })
  it('separates fixed expected money, variable ranges, recorded occurrences and pending candidates', () => {
    let state = createRecurringState()
    for (const item of recurringPatterns.filter(item => !item.ambiguous)) state = decide(state, item.id)
    const result = overview(state)
    expect(result.fixed.minor).toBe(590n); expect(result.fixedCount).toBe(1); expect(result.variableCount).toBe(1)
    expect(result.expected.map(row => row.pattern.id)).toEqual(['service-fee', 'grocery-top-up'])
    expect(result.rows.find(row => row.pattern.id === 'rent')?.status).toBe('Recorded')
    expect(result.rows.find(row => row.pattern.id === 'home-purchases')?.status).toBe('Pending source')
    expect(result.rows.find(row => row.pattern.id === 'home-purchases')?.observed).toEqual([])
    expect(result.rows.find(row => row.pattern.id === 'grocery-top-up')?.evidence.min).toBe(180000n)
    expect(result.rows.find(row => row.pattern.id === 'grocery-top-up')?.evidence.max).toBe(220000n)
    for (const month of ['2026-08', '2026-09'] as const) { expect(overview(state, records, review, month).expected).toEqual([]); expect(overview(state, records, review, month).historical).toBe(true) }
  })
  it('does not confirm ambiguous associations but permits dismissal/restoration', () => {
    let state = decide(createRecurringState(), 'home-purchases')
    expect(state.error).toBe(true); expect(state.history).toEqual([])
    state = decide(state, 'home-purchases', 'dismiss'); expect(state.decisions['home-purchases']).toBe('dismissed')
    state = decide(state, 'home-purchases', 'restore'); expect(state.decisions['home-purchases']).toBeUndefined()
    expect(evidence('home-purchases').valid).toBe(false)
  })
  it('undoes confirm/dismiss/restore in order and resets only recurring decisions', () => {
    let state = decide(createRecurringState(), 'service-fee')
    state = decide(state, 'service-fee', 'dismiss'); state = decide(state, 'service-fee', 'restore')
    state = changeRecurring(state, { type: 'undo' }, records, review); expect(state.decisions['service-fee']).toBe('dismissed')
    state = changeRecurring(state, { type: 'undo' }, records, review); expect(state.decisions['service-fee']).toBe('confirmed')
    state = changeRecurring(state, { type: 'undo' }, records, review); expect(state.decisions['service-fee']).toBeUndefined()
    expect(changeRecurring(state, { type: 'undo' }, records, review).history).toEqual([])
    expect(changeRecurring(decide(state, 'rent'), { type: 'reset' }, records, review).decisions).toEqual({})
    expect(decide(decide(state, 'rent'), 'rent').history).toHaveLength(1)
    const changed = decide(state, 'rent'); changed.decisions.rent = 'dismissed'
    expect(changeRecurring(changed, { type: 'undo' }, records, review).error).toBe(true)
  })
  it('revalidates action evidence after source or classification changes', () => {
    const action = { type: 'confirm' as const, id: 'rent', evidence: evidence('rent').key }
    const source = records.filter(item => item.id !== 't30')
    expect(changeRecurring(createRecurringState(), action, source, review).error).toBe(true)
    const changed = changeTransfers(review, { type: 'categorize', preview: previewCategories(['t30'], 'health', records, review) }, records)
    expect(evidence('rent', records, changed).valid).toBe(true)
    expect(changeRecurring(createRecurringState(), action, records, changed).error).toBe(true)
    expect(changeRecurring(createRecurringState(), { ...action, id: '__proto__' }, records, review).error).toBe(true)
  })
  it('retains confirmations but excludes changed classifications; undo restores evidence', () => {
    const state = decide(createRecurringState(), 'service-fee')
    let changed = changeTransfers(review, { type: 'categorize', preview: previewCategories(['t42'], 'unresolved', records, review) }, records)
    let result = overview(state, records, changed)
    expect(result.fixed.minor).toBe(0n); expect(result.rows.find(row => row.pattern.id === 'service-fee')?.needsReview).toBe(true)
    expect(state.decisions['service-fee']).toBe('confirmed')
    changed = changeTransfers(changed, { type: 'undo' }, records)
    expect(overview(state, records, changed).fixed.minor).toBe(590n)
  })
  it('keeps missing-source occurrences unknown, retains decisions and recovers without duplicates', () => {
    const state = decide(decide(createRecurringState(), 'maintenance'), 'service-fee')
    const partial = overview(state, getBankTransactions(true, null), review, '2026-10', true)
    const row = partial.rows.find(row => row.pattern.id === 'maintenance')!
    expect(row.status).toBe('Unknown'); expect(row.needsReview).toBe(true); expect(row.decision).toBe('confirmed')
    expect(partial.fixed.minor).toBe(0n)
    expect(overview(state).fixed.minor).toBe(590n); expect(overview(state).rows.find(row => row.pattern.id === 'maintenance')?.status).toBe('Recorded')
    expect(state.history).toHaveLength(2)
  })
  it.each([
    { counterparty: 'Different payee' }, { ownerId: 'another-owner' }, { accountId: 'sbi' as const }, { sourceId: 'replacement' },
    { date: '2026-08-03' }, { amount: money('22000.01') }, { status: 'pending' as const }, { direction: 'credit' as const },
    { narration: 'Changed source text' }, { reference: 'Changed reference' }, { sourceCategory: 'investment' as const },
  ])('invalidates changed source identity case %#', patch => {
    const source = records.map(item => item.id === 't30' ? { ...item, ...patch } : item)
    expect(evidence('rent', source).valid).toBe(false)
    const state = decide(createRecurringState(), 'rent')
    expect(overview(state, source).rows.find(row => row.pattern.id === 'rent')?.needsReview).toBe(true)
  })
  it('rejects reused records, duplicate source IDs, overlapping patterns and same-month repeats', () => {
    for (const ids of [['t30'], ['t30', 't30'], ['t05', 't06']]) { const p = fromIds(ids); expect(recurringEvidence(p, records, review, [p]).valid).toBe(false) }
    expect(evidence('rent', [...records, records.find(item => item.id === 't30')!]).valid).toBe(false)
    const duplicate = { ...pattern('rent'), id: 'another-pattern' }
    expect(recurringEvidence(pattern('rent'), records, review, [...recurringPatterns, duplicate]).valid).toBe(false)
  })
  it.each(['pending', 'transfer', 'investment', 'refund', 'unresolved', 'foreign', 'negative', 'future'])('does not establish an expense occurrence from %s', kind => {
    const p = pattern('service-fee')
    const source = records.map(item => item.id !== 't42' ? item : {
      ...item, status: kind === 'pending' ? 'pending' : item.status,
      sourceCategory: ['transfer', 'investment', 'refund', 'unresolved'].includes(kind) ? kind : item.sourceCategory,
      amount: kind === 'foreign' ? money('5.90', 'USD') : kind === 'negative' ? money('-5.90') : item.amount,
      date: kind === 'future' ? '2026-11-22' : item.date,
    } as BankTransaction)
    const bound = { ...p, occurrences: p.occurrences.map(occ => occ.id !== 't42' ? occ : { ...occ, source: recurringSourceKey(source.find(item => item.id === 't42')!) }) }
    expect(recurringEvidence(bound, source, review, [bound]).valid).toBe(false)
  })
  it('invalidates retained transfer membership even if the pair is incomplete', () => {
    const changed = { ...review, pairs: [...review.pairs, { id: 'test', debitId: 't42', creditId: 't20' }] }
    expect(evidence('service-fee', records, changed).valid).toBe(false)
  })
  it('distinguishes an unobserved historical occurrence from unknown coverage and unsupported months', () => {
    const p = { ...pattern('service-fee'), occurrences: [pattern('rent').occurrences[1]!, pattern('rent').occurrences[2]!], accountId: 'hdfc' as const, payee: 'Sample home' }
    const check = (coverage = bankCoverage()) => recurringOverview(records, review, createRecurringState(), '2026-08', coverage, [p])!
    expect(check().rows[0]?.status).toBe('Not observed in available records')
    expect(check([]).rows[0]?.status).toBe('Unknown')
    expect(recurringOverview(records, review, createRecurringState(), '2026-11' as CashMonth)).toBeNull()
  })
  it('does not alter source data, reconciliations, monthly actuals, cash flow or assets', () => {
    const before = structuredClone(records), snapshots = getBankSnapshots(false, null)
    const budgets = budgetOverview(createBudgetState(), records, review, false), cash = cashFlow(records, review, '2026-10-01', '2026-10-20')
    let state = createRecurringState()
    for (const p of recurringPatterns) { state = decide(state, p.id); state = decide(state, p.id, 'dismiss'); state = changeRecurring(state, { type: 'undo' }, records, review) }
    overview(state)
    expect(records).toEqual(before); expect(budgetOverview(createBudgetState(), records, review, false)).toEqual(budgets)
    expect(cashFlow(records, review, '2026-10-01', '2026-10-20')).toEqual(cash)
    expect(cash.spending.minor).toBe(3596490n); expect(cash.movement.minor).toBe(4578510n)
    for (const snapshot of snapshots) expect(bankReconciliation(snapshot, records).difference?.minor).toBe(0n)
    expect(getSummary(getPositions()).total.minor).toBe(508608000n)
  })
})

describe('monthly calendar dates', () => {
  it.each([['2026-01', 31, '2026-01-31'], ['2026-02', 31, '2026-02-28'], ['2028-02', 31, '2028-02-29'], ['2100-02', 31, '2100-02-28'], ['2000-02', 31, '2000-02-29'], ['2026-04', 31, '2026-04-30'], ['2026-05', 31, '2026-05-31'], ['2026-10', 2, '2026-10-02']])('clamps %s day %s without changing future recurrence', (month, day, expected) => expect(recurringDate(month as string, day as number)).toBe(expected))
  it.each([['2026-13', 1], ['2026-00', 1], ['2026-1', 1], ['2026-01-01', 1], ['0000-01', 1], ['2026-01', 0], ['2026-01', 32], ['2026-01', 1.2], ['2026-01', NaN]])('rejects unsupported dates %s / %s', (month, day) => expect(recurringDate(month as string, day as number)).toBeNull())
})
