import { bankOwners, BANK_PERIOD, getBankTransactions } from './banking'
import type { BankId, BankTransaction } from './banking'
import { expenseCategories } from './categories'
import { bankCoverage, cashMonths, coverageFor, monthWindow } from './cashFlow'
import type { CashMonth, CoverageInterval } from './cashFlow'
import { money, sum } from './money'
import { effectiveClassification } from './transfers'
import type { TransferState } from './transfers'

export interface RecurringPattern {
  id: string; name: string; accountId: BankId; ownerId: string; payee: string; day: number
  kind: 'fixed' | 'variable'; reason: string; ambiguous?: string
  occurrences: readonly { month: string; id: string; source: string }[]
  related: readonly { id: string; source: string }[]
}
// Full source identity is kept in memory only. Payee and narrative changes cannot reuse a decision.
export function recurringSourceKey(item: BankTransaction) {
  return JSON.stringify([item.id, item.accountId, item.ownerId, item.sourceId, item.date, item.valueDate,
    item.direction, item.amount.currency, item.amount.minor.toString(), item.status, item.sourceCategory,
    item.counterparty, item.description, item.narration, item.reference, item.transferReference])
}
const source = getBankTransactions(false, null)
function supplied(id: string, name: string, ids: string[], day: number, kind: RecurringPattern['kind'], reason: string, relatedIds: string[] = [], ambiguous?: string): RecurringPattern {
  const first = source.find(item => item.id === ids[0])!
  return { id, name, day, kind, reason, ambiguous, accountId: first.accountId, ownerId: first.ownerId, payee: first.counterparty,
    occurrences: ids.map(id => { const item = source.find(item => item.id === id)!; return { id, month: item.date.slice(0, 7), source: recurringSourceKey(item) } }),
    related: relatedIds.map(id => ({ id, source: recurringSourceKey(source.find(item => item.id === id)!) })) }
}
export const recurringPatterns: readonly RecurringPattern[] = [
  supplied('rent', 'Home rent', ['t30', 't45', 't02'], 2, 'fixed', 'Three monthly rent records, with the same payee and amount. Supplied schedule: day 2.'),
  supplied('electricity', 'Electricity', ['t31', 't46', 't03'], 3, 'variable', 'Three monthly utility bills. Amounts vary; the observed range is not a quote. Supplied schedule: day 3.'),
  supplied('subscription', 'Monthly subscription', ['t39', 't55', 't23'], 15, 'fixed', 'Three monthly subscription records, with the same payee and amount. Supplied schedule: day 15.'),
  supplied('maintenance', 'Water & maintenance', ['t41', 't57', 't26'], 19, 'variable', 'Three monthly service bills. Partial mode omits the October source. Supplied schedule: day 19.'),
  supplied('service-fee', 'Monthly service fee', ['t42', 't58'], 22, 'fixed', 'Two monthly SBI service fees. The separate HDFC transfer fee is unrelated. Supplied schedule: day 22.'),
  supplied('grocery-top-up', 'Grocery top-up', ['t36', 't50'], 28, 'variable', 'Two late-month top-ups on days 28 and 26. Supplied schedule: day 28; regular grocery trips are separate.'),
  supplied('home-purchases', 'Home purchases', ['t33', 't52'], 12, 'variable', 'Two monthly purchases from the same store are possible evidence, but do not establish a contract.', ['t07', 't16'], 'October has a posted purchase and a pending purchase at this store. Neither is assigned to a monthly occurrence; the association is ambiguous.'),
]

export type RecurringDecision = 'confirmed' | 'dismissed'
export interface RecurringState {
  decisions: Record<string, RecurringDecision | undefined>
  history: { id: string; before?: RecurringDecision; after?: RecurringDecision }[]
  message: string; error: boolean
}
export interface RecurringControls { month: CashMonth; filter: 'all' | 'suggestions' | 'confirmed' | 'dismissed'; expanded: string | null }
export const initialRecurringControls: RecurringControls = { month: '2026-10', filter: 'all', expanded: null }
export function createRecurringState(): RecurringState { return { decisions: {}, history: [], message: '', error: false } }
export type RecurringAction = { type: 'confirm' | 'dismiss' | 'restore'; id: string; evidence: string } | { type: 'undo' } | { type: 'reset' }

// UTC calendar arithmetic, independent of the machine date and time zone. Never change the rule's day.
export function recurringDate(month: string, day: number): string | null {
  if (!/^[1-9]\d{3}-(0[1-9]|1[0-2])$/.test(month) || !Number.isInteger(day) || day < 1 || day > 31) return null
  const [year, number] = month.split('-').map(Number)
  const last = new Date(Date.UTC(year!, number!, 0)).getUTCDate()
  return `${month}-${String(Math.min(day, last)).padStart(2, '0')}`
}
function identity(item: BankTransaction, pattern: RecurringPattern) {
  return Object.hasOwn(bankOwners, item.accountId) && bankOwners[item.accountId] === item.ownerId
    && item.ownerId === pattern.ownerId && item.accountId === pattern.accountId && item.counterparty === pattern.payee
    && item.direction === 'debit' && item.amount.currency === 'INR' && item.amount.minor > 0n
}
function postedExpense(item: BankTransaction, pattern: RecurringPattern, records: readonly BankTransaction[], review: TransferState) {
  return identity(item, pattern) && item.status === 'posted' && item.date <= BANK_PERIOD.to
    && expenseCategories.includes(effectiveClassification(item, records, review).category)
}
export function recurringEvidence(pattern: RecurringPattern, records: readonly BankTransaction[], review: TransferState, patterns = recurringPatterns) {
  const issues: string[] = []
  const ids = pattern.occurrences.map(item => item.id), months = pattern.occurrences.map(item => item.month)
  if (ids.length < 2 || new Set(months).size !== months.length || new Set(ids).size !== ids.length) issues.push('At least two separate monthly occurrences are required, with one source per occurrence.')
  if (patterns.some(other => other.id !== pattern.id && other.occurrences.some(item => ids.includes(item.id)))) issues.push('An occurrence is already assigned to another pattern.')
  if (new Set(patterns.map(item => item.id)).size !== patterns.length || !recurringDate('2026-10', pattern.day)) issues.push('The supplied pattern identity or schedule is invalid.')
  const observations = pattern.occurrences.map(occurrence => {
    const matches = records.filter(item => item.id === occurrence.id), item = matches.length === 1 ? matches[0] : undefined
    const valid = !!item && recurringSourceKey(item) === occurrence.source && item.date.slice(0, 7) === occurrence.month && postedExpense(item, pattern, records, review)
    if (!valid) issues.push(`${occurrence.id}: source missing, changed, duplicated, or no longer an eligible expense.`)
    return { ...occurrence, item, valid }
  })
  const related = pattern.related.map(reference => {
    const matches = records.filter(item => item.id === reference.id), item = matches.length === 1 ? matches[0] : undefined
    const valid = !!item && recurringSourceKey(item) === reference.source && identity(item, pattern)
    if (!valid) issues.push(`${reference.id}: related source is missing or changed.`)
    return { ...reference, item, valid }
  })
  const amounts = observations.filter(item => item.valid).map(item => item.item!.amount.minor)
  const min = amounts.length ? amounts.reduce((a, b) => a < b ? a : b) : null, max = amounts.length ? amounts.reduce((a, b) => a > b ? a : b) : null
  if (pattern.kind === 'fixed' && min !== max) issues.push('The recorded amounts no longer support a fixed amount.')
  if (pattern.ambiguous) issues.push(pattern.ambiguous)
  const key = JSON.stringify([pattern, [...observations, ...related].map(item => [item.id, item.item ? recurringSourceKey(item.item) : null, item.item ? effectiveClassification(item.item, records, review) : null]), issues])
  return { valid: issues.length === 0, issues, observations, related, min, max, key }
}
export function changeRecurring(state: RecurringState, action: RecurringAction, records: readonly BankTransaction[], review: TransferState): RecurringState {
  const fail = (message: string) => ({ ...state, message, error: true })
  if (action.type === 'reset') return { ...createRecurringState(), message: 'Sample recurring decisions reset. Budgets and banking reviews are unchanged.' }
  if (action.type === 'undo') {
    const last = state.history.at(-1)
    if (!last) return { ...state, message: 'No recurring change to undo.', error: false }
    if (state.decisions[last.id] !== last.after) return fail('The recurring decision changed. This change cannot be undone.')
    const decisions = { ...state.decisions }
    if (last.before) decisions[last.id] = last.before; else delete decisions[last.id]
    return { decisions, history: state.history.slice(0, -1), message: 'Recurring change undone. Source records are unchanged.', error: false }
  }
  const pattern = recurringPatterns.find(item => item.id === action.id)
  if (!pattern) return fail('This recurring suggestion is unavailable.')
  const evidence = recurringEvidence(pattern, records, review)
  if (evidence.key !== action.evidence) return fail('The evidence changed. Review the current sources before applying this decision.')
  const before = state.decisions[pattern.id]
  if (action.type === 'confirm' && (!evidence.valid || before)) return fail('This suggestion cannot be confirmed. Review its evidence first.')
  if ((action.type === 'restore' && before !== 'dismissed') || (action.type === 'dismiss' && before === 'dismissed')) return fail('The decision changed. Review the current suggestion.')
  const after = action.type === 'confirm' ? 'confirmed' : action.type === 'dismiss' ? 'dismissed' : undefined
  const decisions = { ...state.decisions }
  if (after) decisions[pattern.id] = after; else delete decisions[pattern.id]
  return { decisions, history: [...state.history, { id: pattern.id, before, after }], error: false,
    message: after === 'confirmed' ? 'Recurring pattern confirmed. No payment or transaction was created.' : after === 'dismissed' ? 'Suggestion dismissed. Recorded expenses are unchanged.' : 'Suggestion restored for review.' }
}

export type OccurrenceStatus = 'Recorded' | 'Pending source' | 'Expected' | 'Not observed in available records' | 'Unknown' | 'Needs review' | 'Unconfirmed'
export function recurringOverview(records: readonly BankTransaction[], review: TransferState, state: RecurringState, month: CashMonth, coverage: readonly CoverageInterval[] = bankCoverage(), patterns = recurringPatterns) {
  if (!cashMonths.includes(month)) return null
  const rows = patterns.map(pattern => {
    const evidence = recurringEvidence(pattern, records, review, patterns), decision = state.decisions[pattern.id]
    const due = recurringDate(month, pattern.day)!
    const observed = evidence.observations.filter(item => item.month === month)
    const related = evidence.related.filter(item => item.valid && item.item!.date.slice(0, 7) === month)
    const pending = related.filter(item => item.item!.status === 'pending')
    const future = month === BANK_PERIOD.to.slice(0, 7) && due > BANK_PERIOD.to
    const window = monthWindow(month)
    const complete = coverageFor(window.from, window.to, pattern.accountId, coverage).complete
    let status: OccurrenceStatus
    if (observed.some(item => item.valid)) status = 'Recorded'
    else if (pending.length) status = 'Pending source'
    else if (observed.length || !complete) status = 'Unknown'
    else if (!evidence.valid) status = 'Needs review'
    else if (future) status = decision === 'confirmed' ? 'Expected' : 'Unconfirmed'
    else status = 'Not observed in available records'
    const expected = future && status === 'Expected' && evidence.valid && decision === 'confirmed'
    return { pattern, evidence, decision, due, observed, related, pending, status, expected, complete,
      needsReview: !evidence.valid, fixed: expected && pattern.kind === 'fixed' && evidence.min !== null ? { ...money('0'), minor: evidence.min } : null }
  })
  const expected = rows.filter(row => row.expected)
  return { rows, expected, fixed: sum(expected.flatMap(row => row.fixed ? [row.fixed] : [])), fixedCount: expected.filter(row => row.fixed).length,
    variableCount: expected.filter(row => row.pattern.kind === 'variable').length, reviewed: rows.filter(row => row.decision === 'confirmed').length,
    needsReview: rows.filter(row => row.needsReview && row.decision !== 'dismissed').length, historical: month !== BANK_PERIOD.to.slice(0, 7) }
}
