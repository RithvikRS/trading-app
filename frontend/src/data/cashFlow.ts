import { bankOwners, getBankSnapshots } from './banking'
import type { BankCategory, BankId, BankTransaction } from './banking'
import { expenseCategories, incomeCategories, refundEvidence } from './categories'
import { effectiveClassification } from './transfers'
import type { TransferState } from './transfers'
import { divideRounded, money } from './money'

export const cashMonths = ['2026-08', '2026-09', '2026-10'] as const
export type CashMonth = typeof cashMonths[number]
export type CashAccount = BankId | ''
export interface CashControls { month: CashMonth; account: CashAccount; day: string | null; category: BankCategory | ''; table: boolean; sourcesOpen: boolean }
export const initialCashControls: CashControls = { month: '2026-10', account: '', day: null, category: '', table: false, sourcesOpen: false }
export const monthNames: Record<CashMonth, string> = { '2026-08': 'August 2026', '2026-09': 'September 2026', '2026-10': 'October 2026' }
export function monthEnd(month: CashMonth) { return `${month}-${month === '2026-09' ? '30' : '31'}` }
export function monthWindow(month: CashMonth) { return { from: `${month}-01`, to: month === '2026-10' ? '2026-10-20' : monthEnd(month) } }
export interface CoverageInterval { accountId: BankId; from: string; to: string; complete: boolean; reason: string }
export function bankCoverage(partial = false): CoverageInterval[] {
  return getBankSnapshots(false, null).flatMap(snapshot => partial && snapshot.sourceId === 'sample-sbi-oct'
    ? [{ accountId: snapshot.accountId, from: snapshot.from, to: '2026-10-18', complete: true, reason: 'Supplied statement interval' },
      { accountId: snapshot.accountId, from: '2026-10-19', to: snapshot.to, complete: false, reason: 'Missing bill on 19 October; stale activity through 20 October' }]
    : [{ accountId: snapshot.accountId, from: snapshot.from, to: snapshot.to, complete: true, reason: 'Supplied statement interval' }])
}
export function calendarDays(from: string, to: string) {
  const days: string[] = []
  for (let day = from; day <= to; day = new Date(Date.parse(`${day}T00:00:00Z`) + 86400000).toISOString().slice(0, 10)) days.push(day)
  return days
}
export function coverageFor(from: string, to: string, account: CashAccount, intervals: readonly CoverageInterval[]) {
  const accounts: BankId[] = account ? [account] : ['hdfc', 'sbi']
  const days = calendarDays(from, to)
  const details = accounts.map(accountId => {
    const covered = days.filter(day => intervals.some(interval => interval.accountId === accountId && interval.complete && interval.from <= day && interval.to >= day))
    return { accountId, covered: covered.length, total: days.length, complete: covered.length === days.length && days.length > 0 }
  })
  return { complete: details.every(item => item.complete), any: details.some(item => item.covered > 0), details }
}
export type CashRole = 'income' | 'expense' | 'refund' | 'investment' | 'transfer' | 'unresolved' | 'pending'
export function cashRole(item: BankTransaction, records: readonly BankTransaction[], review: TransferState): CashRole {
  if (item.status === 'pending') return 'pending'
  const category = effectiveClassification(item, records, review).category
  if (category === 'transfer' || category === 'investment') return category
  if (category === 'refund' && refundEvidence(item, records, review)) return 'refund'
  if (item.direction === 'credit' && incomeCategories.includes(category)) return 'income'
  if (item.direction === 'debit' && expenseCategories.includes(category)) return 'expense'
  return 'unresolved'
}
// Full evidence validates pairs/refunds. Only the selected booking window contributes money.
export function cashFlow(records: readonly BankTransaction[], review: TransferState, from: string, to: string, account: CashAccount = '') {
  const scope = records.filter(item => Object.hasOwn(bankOwners, item.accountId) && bankOwners[item.accountId] === item.ownerId && item.amount.currency === 'INR' && item.amount.minor > 0n && (!account || item.accountId === account) && item.date >= from && item.date <= to)
  const entries = scope.map(item => ({ item, role: cashRole(item, records, review) }))
  const total = (role: CashRole, direction?: 'debit' | 'credit') => ({ ...money('0'), minor: entries.reduce((value, entry) => value + (entry.role === role && (!direction || entry.item.direction === direction) ? entry.item.amount.minor : 0n), 0n) })
  const income = total('income'), gross = total('expense'), refunds = total('refund')
  const spending = { ...gross, minor: gross.minor - refunds.minor }, surplus = { ...income, minor: income.minor - spending.minor }
  const investmentIn = total('investment', 'credit'), investmentOut = total('investment', 'debit'), transferIn = total('transfer', 'credit'), transferOut = total('transfer', 'debit'), unresolvedIn = total('unresolved', 'credit'), unresolvedOut = total('unresolved', 'debit')
  const movement = { ...income, minor: entries.reduce((value, { item, role }) => value + (role === 'pending' ? 0n : item.amount.minor * (item.direction === 'credit' ? 1n : -1n)), 0n) }
  const bridge = { ...income, minor: surplus.minor + investmentIn.minor - investmentOut.minor + transferIn.minor - transferOut.minor + unresolvedIn.minor - unresolvedOut.minor }
  return { entries, income, gross, refunds, spending, surplus, investmentIn, investmentOut, transferIn, transferOut, unresolvedIn, unresolvedOut, movement, bridge,
    unresolved: entries.filter(entry => entry.role === 'unresolved').length, pending: entries.filter(entry => entry.role === 'pending').length, pendingIn: total('pending', 'credit'), pendingOut: total('pending', 'debit') }
}
export function comparablePeriod(month: CashMonth, account: CashAccount, records: readonly BankTransaction[], review: TransferState, coverage: readonly CoverageInterval[]) {
  const previous = cashMonths[cashMonths.indexOf(month) - 1]
  if (!previous) return { reason: 'July history is not supplied. A prior-period comparison is unavailable.' } as const
  const count = Math.min(Number(monthWindow(month).to.slice(-2)), Number(monthWindow(previous).to.slice(-2)))
  const currentWindow = { from: `${month}-01`, to: `${month}-${String(count).padStart(2, '0')}` }
  const priorWindow = { from: `${previous}-01`, to: `${previous}-${String(count).padStart(2, '0')}` }
  const current = cashFlow(records, review, currentWindow.from, currentWindow.to, account), prior = cashFlow(records, review, priorWindow.from, priorWindow.to, account)
  const reason = !coverageFor(currentWindow.from, currentWindow.to, account, coverage).complete || !coverageFor(priorWindow.from, priorWindow.to, account, coverage).complete
    ? 'Comparison unavailable: both windows need complete source coverage for the same accounts.'
    : current.unresolved || prior.unresolved ? 'Comparison unavailable: posted movements still need classification in one or both windows.' : null
  const changes = (['income', 'spending', 'surplus'] as const).map(key => {
    const delta = current[key].minor - prior[key].minor, base = prior[key].minor < 0n ? -prior[key].minor : prior[key].minor
    return { key, delta: { ...current[key], minor: delta }, basisPoints: base === 0n ? null : divideRounded(delta * 10000n, base) }
  })
  return { reason, currentWindow, priorWindow, count, changes: reason ? null : changes }
}
