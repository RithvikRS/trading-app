import { bankOwners, BANK_PERIOD } from './banking'
import type { BankCategory, BankTransaction } from './banking'
import { expenseCategories, refundEvidence } from './categories'
import { effectiveClassification } from './transfers'
import type { TransferState } from './transfers'
import { money, sum } from './money'

export const budgetScope = { ownerId: 'sample-owner', month: '2026-10', currency: 'INR' } as const
const sampleLimits: Partial<Record<BankCategory, bigint>> = {
  housing: 2200000n, utilities: 450000n, groceries: 600000n, dining: 120000n,
  shopping: 300000n, transport: 100000n, health: 0n, subscriptions: 49900n,
}
export interface BudgetState {
  ownerId: string; month: string; limits: Partial<Record<BankCategory, bigint>>
  history: { category: BankCategory; before?: bigint; after?: bigint }[]; message: string
}
export type BudgetAction = { type: 'set'; category: BankCategory; decimal: string } | { type: 'remove'; category: BankCategory } | { type: 'undo' } | { type: 'reset' }
export function createBudgetState(withSample = true): BudgetState {
  return { ownerId: budgetScope.ownerId, month: budgetScope.month, limits: withSample ? { ...sampleLimits } : {}, history: [], message: '' }
}
export function parseBudgetLimit(input: string): { minor: bigint; error?: never } | { minor?: never; error: string } {
  if (input.length > 32) return { error: 'Use a shorter amount, with at most two decimal places.' }
  const value = input.trim()
  if (!/^\d{1,9}(\.\d{1,2})?$/.test(value)) return { error: 'Enter 0 to 999999999.99 in INR, using digits and an optional decimal point. Do not use commas or more than two decimal places.' }
  return { minor: money(value).minor }
}
export function changeBudgets(state: BudgetState, action: BudgetAction): BudgetState {
  if (action.type === 'reset') return { ...createBudgetState(), message: 'Sample budgets reset. Banking decisions are unchanged.' }
  if (state.ownerId !== budgetScope.ownerId || state.month !== budgetScope.month) return { ...state, message: 'This budget scope is unavailable.' }
  if (action.type === 'undo') {
    const last = state.history.at(-1)
    if (!last) return { ...state, message: 'No budget change to undo.' }
    if (state.limits[last.category] !== last.after) return { ...state, message: 'The budget has changed. This change cannot be undone.' }
    const limits = { ...state.limits }
    if (last.before === undefined) delete limits[last.category]; else limits[last.category] = last.before
    return { ...state, limits, history: state.history.slice(0, -1), message: 'Budget change undone. Source records are unchanged.' }
  }
  if (!expenseCategories.includes(action.category)) return { ...state, message: 'Choose an expense category.' }
  const parsed = action.type === 'set' ? parseBudgetLimit(action.decimal) : null
  if (parsed?.error) return { ...state, message: 'The limit is invalid. Review the amount before saving.' }
  const before = state.limits[action.category], after = parsed?.minor
  if (before === after) return { ...state, message: 'Budget unchanged.' }
  const limits = { ...state.limits }
  if (after === undefined) delete limits[action.category]; else limits[action.category] = after
  return { ...state, limits, history: [...state.history, { category: action.category, before, after }], message: after === undefined ? 'Category limit removed. Actual spending is unchanged.' : 'Category limit saved. Actual spending is unchanged.' }
}

export function monthlyBudgetActuals(records: readonly BankTransaction[], review: TransferState) {
  const scope = records.filter(item => item.ownerId === budgetScope.ownerId && bankOwners[item.accountId] === item.ownerId
    && item.date >= BANK_PERIOD.from && item.date <= BANK_PERIOD.to)
  const posted = scope.filter(item => item.status === 'posted')
  const rows = expenseCategories.map(category => {
    const expenses = posted.filter(item => item.direction === 'debit' && effectiveClassification(item, records, review).category === category)
    const refunds = posted.filter(item => effectiveClassification(item, records, review).category === 'refund' && refundEvidence(item, records, review)?.category === category)
    const gross = sum(expenses.map(item => item.amount)), refunded = sum(refunds.map(item => item.amount))
    return { category, gross, refunded, net: { ...gross, minor: gross.minor - refunded.minor },
      records: [...expenses, ...refunds].sort((a, b) => b.date.localeCompare(a.date) || a.id.localeCompare(b.id)), refundIds: new Set(refunds.map(item => item.id)) }
  })
  const unresolved = posted.filter(item => effectiveClassification(item, records, review).category === 'unresolved')
  return { rows, total: sum(rows.map(row => row.net)), unresolved: unresolved.length,
    outgoing: sum(unresolved.filter(item => item.direction === 'debit').map(item => item.amount)),
    incoming: sum(unresolved.filter(item => item.direction === 'credit').map(item => item.amount)), pending: scope.length - posted.length }
}
export function budgetOverview(state: BudgetState, records: readonly BankTransaction[], review: TransferState, incomplete: boolean) {
  const actuals = monthlyBudgetActuals(records, review)
  const validScope = state.ownerId === budgetScope.ownerId && state.month === budgetScope.month
  const rows = actuals.rows.map(row => {
    const limit = validScope ? state.limits[row.category] : undefined
    return { ...row, limit: limit === undefined ? null : { currency: budgetScope.currency, minor: limit },
      remaining: limit === undefined ? null : { currency: budgetScope.currency, minor: limit - row.net.minor } }
  }).sort((a, b) => Number((b.remaining?.minor ?? 0n) < 0n) - Number((a.remaining?.minor ?? 0n) < 0n))
  const budgeted = rows.filter(row => row.limit !== null)
  const planned = sum(budgeted.map(row => row.limit!)), spent = sum(budgeted.map(row => row.net))
  return { ...actuals, rows, planned, spent, remaining: { ...planned, minor: planned.minor - spent.minor },
    unbudgeted: sum(rows.filter(row => row.limit === null).map(row => row.net)), count: budgeted.length, provisional: incomplete || actuals.unresolved > 0 }
}
export function budgetStatus(net: bigint, limit: bigint | undefined, provisional: boolean) {
  if (limit === undefined) return 'No limit set'
  if (net < 0n) return 'Net refund'
  if (net > limit) return provisional ? 'Over limit · provisional' : 'Over limit'
  if (net === limit) return provisional ? 'At limit · provisional' : 'At limit'
  return provisional ? 'Within limit · provisional' : 'Under limit'
}
