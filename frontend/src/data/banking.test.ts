import { describe, expect, it } from 'vitest'
import { BANK_PERIOD, bankReconciliation, bankReview, bankScope, bankTotals, defaultBankingControls, getBankSnapshots, getBankTransactions, selectBankTransactions, validBankDates } from './banking'
import type { BankingControls, BankingFilters } from './banking'
import { getActivity, getPositions, getSummary } from './portfolio'
import { money, sum } from './money'

const controls = (filters: Partial<BankingFilters> = {}, sort: BankingControls['sort'] = 'date', direction: BankingControls['direction'] = 'desc'): BankingControls => ({ filters: { ...defaultBankingControls.filters, ...filters }, sort, direction })
describe('bank statement fixtures', () => {
  it('reconciles supplied opening balances and posted movements to the shared bank snapshots', () => {
    const records = getBankTransactions()
    expect(records).toHaveLength(28)
    expect(new Set(records.map(item => item.id)).size).toBe(28)
    expect(records.every(item => item.amount.minor > 0n && item.amount.currency === 'INR')).toBe(true)
    for (const snapshot of getBankSnapshots()) expect(bankReconciliation(snapshot, records).difference).toEqual(money('0'))
    expect(bankTotals(records)).toEqual({ credits: money('139050'), debits: money('93264.90'), posted: 26, pending: 2, pendingCredits: money('2000'), pendingDebits: money('1299') })
    expect(sum(getBankSnapshots().map(item => item.balance!))).toEqual(money('261270'))
    expect(getSummary(getPositions())).toEqual({ invested: money('4796290'), cash: money('289790'), total: money('5086080'), missing: 0 })
  })
  it('preserves the independently supplied balance while exposing a partial-period discrepancy', () => {
    const snapshot = getBankSnapshots(true).find(item => item.accountId === 'sbi')!
    expect(snapshot.balance).toEqual(money('74850'))
    expect(snapshot.complete).toBe(false)
    expect(snapshot.activityDate).not.toBe(snapshot.balanceDate)
    expect(bankReconciliation(snapshot, getBankTransactions(true))).toEqual({ calculated: money('77050'), difference: money('-2200') })
    expect(bankReconciliation({ ...snapshot, balance: null }, getBankTransactions()).difference).toBeNull()
    expect(getSummary(getPositions(true)).cash).toEqual(money('289790'))
    expect(getActivity(true).find(item => item.id === 't15')?.value).toEqual(getBankTransactions().find(item => item.id === 't15')?.amount)
  })
  it('treats pending records separately and never deduplicates repeated payments by content', () => {
    expect(bankTotals(selectBankTransactions(getBankTransactions(), controls({ status: 'pending' }))).posted).toBe(0)
    const repeated = selectBankTransactions(getBankTransactions(), controls({ query: ' coffee STOP ' }))
    expect(repeated.map(item => item.id)).toEqual(['t05', 't06'])
    expect(bankTotals(repeated).debits).toEqual(money('360'))
  })
  it('combines literal search and filters without narrowing account/date-range summaries', () => {
    const state = controls({ account: 'hdfc', from: '2026-10-05', to: '2026-10-08', direction: 'debit', status: 'posted', category: 'dining', review: 'recorded', query: 'Sample café' })
    const records = getBankTransactions()
    expect(selectBankTransactions(records, state).map(item => item.id)).toEqual(['t05', 't06'])
    expect(bankTotals(bankScope(records, state.filters))).toMatchObject({ credits: money('800'), debits: money('3560'), posted: 4 })
    expect(selectBankTransactions(records, controls({ query: 'Sample reference 08' })).map(item => item.id)).toEqual(['t08'])
    expect(selectBankTransactions(records, controls({ query: '.*' }))).toHaveLength(0)
    expect(selectBankTransactions(records, controls({ query: '<img>' }))).toHaveLength(0)
  })
  it('uses inclusive booking dates, validates ranges, and never substitutes value dates', () => {
    expect(selectBankTransactions(getBankTransactions(), controls({ from: '2026-10-08', to: '2026-10-08' })).map(item => item.id)).toEqual(['t08'])
    expect(selectBankTransactions(getBankTransactions(), controls({ from: '2026-10-09', to: '2026-10-09' })).map(item => item.id)).toEqual(['t09'])
    for (const range of [{ from: '2026-10-20', to: '2026-10-01' }, { from: '2026-02-30' }, { to: 'invalid' }]) {
      expect(validBankDates(controls(range).filters)).toBe(false)
      expect(selectBankTransactions(getBankTransactions(), controls(range))).toHaveLength(0)
    }
    expect(selectBankTransactions(getBankTransactions(), controls({ from: '', to: '' }))).toHaveLength(28)
    expect(BANK_PERIOD).toEqual({ from: '2026-10-01', to: '2026-10-20' })
  })
  it('sorts native numeric amounts in both directions and breaks ties by stable identity', () => {
    const records = getBankTransactions()
    expect(selectBankTransactions(records, controls({}, 'amount', 'asc'))[0]?.id).toBe('t11')
    expect(selectBankTransactions(records, controls({}, 'amount', 'desc'))[0]?.id).toBe('t01')
    for (const direction of ['asc', 'desc'] as const) expect(selectBankTransactions(records, controls({ query: 'Coffee' }, 'amount', direction)).map(item => item.id)).toEqual(['t05', 't06'])
    expect(selectBankTransactions(records, controls({}, 'description', 'asc'))[0]?.description).toBe('Account movement')
    expect(selectBankTransactions(records, controls({}, 'date', 'asc'))[0]?.date).toBe('2026-10-01')
  })
  it('keeps initial pair evidence separate from filtering and flags a missing counterpart', () => {
    const records = getBankTransactions(), debit = records.find(item => item.id === 't15')!
    expect(selectBankTransactions(records, controls({ account: 'hdfc', review: 'confirmed' })).map(item => item.id)).toEqual(['t15'])
    expect(bankReview(debit, records.filter(item => item.id !== 't25'))).toBe('needs-review')
    expect(bankReview(records.find(item => item.id === 't10')!, records)).toBe('needs-review')
  })
  it('returns isolated source objects without mutating the baseline through selectors', () => {
    const records = getBankTransactions(), snapshots = getBankSnapshots()
    records[0]!.description = 'changed'; records[0]!.amount = money('1'); snapshots[0]!.balance = null
    selectBankTransactions(records, controls({}, 'amount', 'asc'))
    expect(getBankTransactions()[0]?.description).toBe('Monthly salary')
    expect(getBankTransactions()[0]?.amount).toEqual(money('95000'))
    expect(getBankSnapshots()[0]?.balance).toEqual(money('186420'))
  })
})
