import { describe, expect, it } from 'vitest'
import { bankReconciliation, bankTotals, getBankSnapshots, getBankTransactions } from './banking'
import { bankCoverage, calendarDays, cashFlow, cashMonths, comparablePeriod, coverageFor, monthWindow } from './cashFlow'
import { changeTransfers, createTransferState, pairId } from './transfers'
import { previewCategories } from './categories'
import { budgetOverview, createBudgetState } from './budgets'
import { getPositions, getSummary } from './portfolio'
import { money, sum } from './money'

const all = () => getBankTransactions(false, null)
const initial = () => createTransferState()
const october = (records = all(), review = initial(), account: '' | 'hdfc' | 'sbi' = '') => cashFlow(records, review, '2026-10-01', '2026-10-20', account)

describe('cash-flow ledger and coverage', () => {
  it('adds independent reconciled statements, continuous account balances, and preserves October and asset baselines', () => {
    const records = all(), snapshots = getBankSnapshots(false, null)
    expect(records).toHaveLength(58); expect(new Set(records.map(item => item.id)).size).toBe(58)
    expect(getBankTransactions()).toHaveLength(28)
    for (const snapshot of snapshots) expect(bankReconciliation(snapshot, records).difference).toEqual(money('0'))
    for (const account of ['hdfc', 'sbi']) {
      const statements = snapshots.filter(item => item.accountId === account)
      expect(statements[0]!.balance).toEqual(statements[1]!.opening)
      expect(statements[1]!.balance).toEqual(statements[2]!.opening)
    }
    expect(sum(getBankSnapshots().map(item => item.opening))).toEqual(money('215484.90'))
    expect(sum(getBankSnapshots().map(item => item.balance!))).toEqual(money('261270'))
    expect(getSummary(getPositions()).total).toEqual(money('5086080'))
    expect(getBankTransactions().map(item => item.id)).toEqual(Array.from({ length: 28 }, (_, i) => `t${String(i + 1).padStart(2, '0')}`))
  })
  it.each([
    ['2026-08', '90230', '41004.90', '0', '49225.10', '42225.10'],
    ['2026-09', '95240', '38704.90', '1500', '58035.10', '43035.10'],
    ['2026-10', '95250', '36764.90', '800', '59285.10', '45785.10'],
  ] as const)('reconciles %s from known source results, with one role for each entry', (month, income, gross, refunds, surplus, movement) => {
    const period = monthWindow(month), data = cashFlow(all(), initial(), period.from, period.to)
    expect(data.income).toEqual(money(income)); expect(data.gross).toEqual(money(gross)); expect(data.refunds).toEqual(money(refunds))
    expect(data.surplus).toEqual(money(surplus)); expect(data.movement).toEqual(money(movement)); expect(data.bridge).toEqual(data.movement)
    expect(new Set(data.entries.map(entry => entry.item.id)).size).toBe(data.entries.length)
    const source = bankTotals(data.entries.map(entry => entry.item))
    expect(data.movement.minor).toBe(source.credits.minor - source.debits.minor)
  })
  it('keeps pending, unresolved, investment and transfer roles out of income and consumption', () => {
    const data = october()
    expect(data.investmentOut).toEqual(money('15000')); expect(data.transferIn).toEqual(money('25000')); expect(data.transferOut).toEqual(money('25000'))
    expect(data.unresolvedIn).toEqual(money('18000')); expect(data.unresolvedOut).toEqual(money('16500'))
    expect(data.pending).toBe(2); expect(data.pendingIn).toEqual(money('2000')); expect(data.pendingOut).toEqual(money('1299'))
    expect(data.spending).toEqual(budgetOverview(createBudgetState(), all(), initial(), false).total)
  })
  it('reconciles every account/day scope including a single leg, without filtering away its evidence', () => {
    for (const month of cashMonths) for (const day of calendarDays(monthWindow(month).from, monthWindow(month).to)) for (const account of ['', 'hdfc', 'sbi'] as const) {
      const data = cashFlow(all(), initial(), day, day, account)
      expect(data.bridge).toEqual(data.movement)
    }
    expect(october(all(), initial(), 'hdfc').transferOut).toEqual(money('25000'))
    expect(october(all(), initial(), 'hdfc').transferIn).toEqual(money('0'))
    expect(october(all().filter(item => item.id !== 't25')).transferOut).toEqual(money('0'))
    expect(october(all().filter(item => item.id !== 't25')).unresolvedOut).toEqual(money('41500'))
  })
  it('validates transfers across month boundaries using full evidence', () => {
    const records = all().map(item => item.id === 't15' ? { ...item, date: '2026-08-31' } : item.id === 't25' ? { ...item, date: '2026-09-01' } : item)
    const august = cashFlow(records, initial(), '2026-08-01', '2026-08-31'), september = cashFlow(records, initial(), '2026-09-01', '2026-09-30')
    expect(august.transferOut).toEqual(money('25000')); expect(september.transferIn).toEqual(money('25000'))
    expect(august.bridge).toEqual(august.movement); expect(september.bridge).toEqual(september.movement)
  })
  it('books cross-month refunds once, supports negative spending, and revalidates linked purchase corrections', () => {
    const records = all(), day = () => cashFlow(records, state, '2026-09-05', '2026-09-05')
    let state = initial()
    expect(day().spending).toEqual(money('-1500')); expect(day().surplus).toEqual(money('1500'))
    state = changeTransfers(state, { type: 'categorize', preview: previewCategories(['t33'], 'health', records, state) }, records)
    expect(day().spending).toEqual(money('-1500'))
    state = changeTransfers(state, { type: 'categorize', preview: previewCategories(['t33'], 'unresolved', records, state) }, records)
    expect(day().refunds).toEqual(money('0')); expect(day().unresolvedIn).toEqual(money('1500'))
    state = changeTransfers(state, { type: 'undo' }, records)
    expect(day().refunds).toEqual(money('1500'))
    const orphan = cashFlow(records.filter(item => item.id !== 't33'), state, '2026-09-05', '2026-09-05')
    expect(orphan.unresolvedIn).toEqual(money('1500')); expect(orphan.bridge).toEqual(orphan.movement)
  })
  it('updates current and historical analytics through shared category and transfer decisions, undo, and reset', () => {
    const records = all(); let state = initial()
    const baseline = october(records, state)
    state = changeTransfers(state, { type: 'categorize', preview: previewCategories(['t13'], 'shopping', records, state) }, records)
    expect(october(records, state).spending).toEqual(money('39464.90')); expect(october(records, state).movement).toEqual(baseline.movement)
    state = changeTransfers(state, { type: 'confirm', pair: { id: pairId('t10', 't20'), debitId: 't10', creditId: 't20' } }, records)
    expect(october(records, state).transferIn).toEqual(money('33000')); expect(october(records, state).spending).toEqual(money('39464.90'))
    state = changeTransfers(state, { type: 'undo' }, records); state = changeTransfers(state, { type: 'undo' }, records)
    expect(october(records, state)).toEqual(baseline)
    expect(october(records, changeTransfers(state, { type: 'reset' }, records))).toEqual(baseline)
  })
  it('distinguishes known zero, gaps, absent history, and incomplete source from classification', () => {
    const complete = bankCoverage(), partial = bankCoverage(true)
    expect(coverageFor('2026-09-04', '2026-09-04', '', complete).complete).toBe(true)
    expect(cashFlow(all(), initial(), '2026-09-04', '2026-09-04').movement).toEqual(money('0'))
    expect(coverageFor('2026-07-01', '2026-07-31', '', complete).any).toBe(false)
    expect(coverageFor('2026-10-21', '2026-10-31', '', complete).any).toBe(false)
    expect(coverageFor('2026-10-19', '2026-10-20', 'sbi', partial).complete).toBe(false)
    expect(coverageFor('2026-10-19', '2026-10-20', 'hdfc', partial).complete).toBe(true)
    expect(coverageFor('2026-10-01', '2026-10-20', '', complete).complete).toBe(true)
    expect(october().unresolved).toBe(6)
  })
  it('shows available partial activity without inventing a balancing adjustment or changing balances', () => {
    const records = getBankTransactions(true, null), data = october(records)
    expect(data.spending).toEqual(money('33764.90')); expect(data.movement).toEqual(money('47985.10')); expect(data.bridge).toEqual(data.movement)
    const sbi = getBankSnapshots(true).find(item => item.accountId === 'sbi')!
    expect(sbi.balance).toEqual(money('74850')); expect(bankReconciliation(sbi, records).difference).toEqual(money('-2200'))
    expect(cashFlow(records, initial(), '2026-09-01', '2026-09-30').movement).toEqual(money('43035.10'))
  })
  it('compares equal calendar windows only with complete coverage and classified posted activity', () => {
    const september = comparablePeriod('2026-09', '', all(), initial(), bankCoverage())
    expect(september.reason).toBeNull(); expect(september.count).toBe(30)
    expect(september.priorWindow?.to).toBe('2026-08-30')
    expect(september.changes?.find(item => item.key === 'income')?.delta).toEqual(money('5010'))
    expect(comparablePeriod('2026-10', '', all(), initial(), bankCoverage()).reason).toContain('classification')
    expect(comparablePeriod('2026-10', '', all(), initial(), bankCoverage(true)).reason).toContain('source coverage')
    expect(comparablePeriod('2026-08', '', all(), initial(), bankCoverage()).reason).toContain('July history')
    const state = changeTransfers(initial(), { type: 'categorize', preview: previewCategories(['t10', 't12', 't13'], 'other-expense', all(), initial()) }, all())
    const compared = comparablePeriod('2026-10', 'hdfc', all(), state, bankCoverage(true))
    expect(compared.reason).toBeNull(); expect(compared.count).toBe(20); expect(compared.priorWindow?.to).toBe('2026-09-20')
    expect(compared.changes?.find(item => item.key === 'spending')?.delta).toEqual(money('15865.90'))
  })
  it('does not divide by a zero comparison base or treat missing coverage as a zero baseline', () => {
    const noIncome = all().filter(item => item.direction === 'debit')
    const comparison = comparablePeriod('2026-09', 'sbi', noIncome, initial(), bankCoverage())
    expect(comparison.changes?.find(item => item.key === 'income')?.basisPoints).toBeNull()
    expect(comparablePeriod('2026-09', 'sbi', noIncome, initial(), []).reason).toContain('source coverage')
  })
  it('keeps unknown ownership out of scope and never mutates source records', () => {
    const records = all(), before = structuredClone(records), original = october(records)
    const foreign = { ...records.find(item => item.id === 't01')!, id: 'foreign', ownerId: 'someone-else' }
    expect(october([...records, foreign])).toEqual(original)
    expect(records).toEqual(before)
  })
})
