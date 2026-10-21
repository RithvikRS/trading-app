import { money, sum } from './money'
import type { Money } from './money'

export const BANK_PERIOD = { from: '2026-10-01', to: '2026-10-20' }
export const BANK_SNAPSHOT = '2026-10-20T04:30:00Z'
export type BankId = 'hdfc' | 'sbi'
export const bankNames: Record<BankId, string> = { hdfc: 'HDFC Bank', sbi: 'SBI' }
export const bankOwners: Record<BankId, string> = { hdfc: 'sample-owner', sbi: 'sample-owner' }
export const bankCategories = {
  salary: 'Salary', interest: 'Interest', housing: 'Housing', utilities: 'Utilities', transport: 'Transport',
  dining: 'Dining', shopping: 'Shopping', groceries: 'Food & groceries', health: 'Health', subscriptions: 'Subscriptions',
  fee: 'Bank fees', 'other-expense': 'Other expense', 'other-income': 'Other income', investment: 'Investment funding', transfer: 'Internal transfer', refund: 'Refund', unresolved: 'Uncategorized',
}
export type BankCategory = keyof typeof bankCategories
export type BankReview = 'recorded' | 'confirmed' | 'reviewed' | 'needs-review'
export const reviewLabels: Record<BankReview, string> = { recorded: 'Source recorded', confirmed: 'Transfer confirmed', reviewed: 'Category reviewed', 'needs-review': 'Needs review' }
export interface BankTransaction {
  id: string; accountId: BankId; ownerId: string; sourceId: string; date: string; valueDate?: string; transferReference?: string
  direction: 'debit' | 'credit'; amount: Money; status: 'posted' | 'pending'
  description: string; counterparty: string; narration: string; reference: string; sourceCategory: BankCategory
}
export interface BankSnapshot {
  accountId: BankId; sourceId: string; opening: Money; balance: Money | null; balanceDate: string
  activityDate: string; complete: boolean
}
const snapshots: readonly BankSnapshot[] = [
  { accountId: 'hdfc', sourceId: 'sample-hdfc-oct', opening: money('177285.90'), balance: money('186420'), balanceDate: BANK_SNAPSHOT, activityDate: BANK_SNAPSHOT, complete: true },
  { accountId: 'sbi', sourceId: 'sample-sbi-oct', opening: money('38199'), balance: money('74850'), balanceDate: BANK_SNAPSHOT, activityDate: BANK_SNAPSHOT, complete: true },
]
function transaction(id: string, accountId: BankId, date: string, direction: BankTransaction['direction'], amount: string, description: string, counterparty: string, sourceCategory: BankCategory, status: BankTransaction['status'] = 'posted', valueDate?: string): BankTransaction {
  const transferReference = ['t10', 't20'].includes(id) ? 'Sample transfer A' : ['t15', 't25'].includes(id) ? 'Sample transfer B' : undefined
  return { id, accountId, ownerId: bankOwners[accountId], transferReference, sourceId: `sample-${accountId}-oct`, date: `2026-10-${date}`, ...(valueDate ? { valueDate: `2026-10-${valueDate}` } : {}), direction, amount: money(amount), status, description, counterparty, sourceCategory,
    narration: `FICTIONAL RECORD / ${description} / INR ${amount} / ${direction.toUpperCase()}`,
    reference: `Sample reference ${id.slice(1)}` }
}
const transactions: readonly BankTransaction[] = [
  transaction('t01', 'hdfc', '01', 'credit', '95000', 'Monthly salary', 'Sample employer', 'salary'),
  transaction('t02', 'hdfc', '02', 'debit', '22000', 'October rent', 'Sample home', 'housing'),
  transaction('t03', 'hdfc', '03', 'debit', '1850', 'Electricity bill', 'Sample utilities', 'utilities'),
  transaction('t04', 'hdfc', '04', 'debit', '300', 'Metro recharge', 'Sample transit', 'transport'),
  transaction('t05', 'hdfc', '05', 'debit', '180', 'Coffee stop', 'Sample café', 'dining'),
  transaction('t06', 'hdfc', '05', 'debit', '180', 'Coffee stop', 'Sample café', 'dining'),
  transaction('t07', 'hdfc', '06', 'debit', '3200', 'Home essentials', 'Sample store', 'shopping'),
  transaction('t08', 'hdfc', '08', 'credit', '800', 'Partial purchase refund', 'Sample store', 'refund', 'posted', '09'),
  transaction('t09', 'hdfc', '09', 'debit', '15000', 'Investment funding', 'Sample investment account', 'investment'),
  transaction('t10', 'hdfc', '10', 'debit', '8000', 'Account movement', 'Sample account', 'unresolved'),
  transaction('t11', 'hdfc', '10', 'debit', '5.90', 'Transfer service fee', 'Sample bank fee', 'fee'),
  transaction('t12', 'hdfc', '12', 'debit', '5000', 'Account movement', 'Sample account', 'unresolved'),
  transaction('t13', 'hdfc', '14', 'debit', '3500', 'Unresolved payment', 'Sample recipient', 'unresolved'),
  transaction('t14', 'hdfc', '18', 'debit', '2450', 'Everyday groceries', 'Sample market', 'groceries'),
  transaction('t15', 'hdfc', '18', 'debit', '25000', 'Transfer to SBI', 'Own sample SBI account', 'transfer'),
  transaction('t16', 'hdfc', '20', 'debit', '1299', 'Online purchase', 'Sample store', 'shopping', 'pending'),
  transaction('t17', 'sbi', '01', 'credit', '250', 'Savings interest', 'Sample bank interest', 'interest'),
  transaction('t18', 'sbi', '03', 'debit', '1200', 'Broadband bill', 'Sample broadband', 'utilities'),
  transaction('t19', 'sbi', '07', 'debit', '450', 'City cab', 'Sample transport', 'transport'),
  transaction('t20', 'sbi', '11', 'credit', '8000', 'Account movement received', 'Sample account', 'unresolved'),
  transaction('t21', 'sbi', '12', 'credit', '5000', 'Account movement received', 'Sample account', 'unresolved'),
  transaction('t22', 'sbi', '13', 'credit', '5000', 'Account movement received', 'Sample account', 'unresolved'),
  transaction('t23', 'sbi', '15', 'debit', '499', 'Monthly subscription', 'Sample subscription', 'subscriptions'),
  transaction('t24', 'sbi', '16', 'debit', '1600', 'Pharmacy visit', 'Sample pharmacy', 'health'),
  transaction('t25', 'sbi', '18', 'credit', '25000', 'Transfer from HDFC', 'Own sample HDFC account', 'transfer'),
  transaction('t26', 'sbi', '19', 'debit', '2200', 'Water and maintenance bill', 'Sample services', 'utilities'),
  transaction('t27', 'sbi', '20', 'credit', '2000', 'Incoming payment', 'Sample sender', 'unresolved', 'pending'),
  transaction('t28', 'sbi', '19', 'debit', '650', 'Evening meal', 'Sample kitchen', 'dining'),
]

// Initial fixture evidence. Interactive decisions live separately from source records.
export const sampleTransfer = { id: 'sample-pair-a', debitId: 't15', creditId: 't25' } as const
export const sampleRefund = { creditId: 't08', purchaseId: 't07' } as const
export function isBankTransactionId(id: string) { return transactions.some(item => item.id === id) }
export function getBankTransactions(partial = false): BankTransaction[] {
  return transactions.filter(item => !partial || item.id !== 't26').map(item => ({ ...item, amount: { ...item.amount } }))
}
export function getBankSnapshots(partial = false): BankSnapshot[] {
  return snapshots.map(item => ({ ...item, opening: { ...item.opening }, balance: item.balance ? { ...item.balance } : null,
    ...(partial && item.accountId === 'sbi' ? { activityDate: '2026-10-19T04:30:00Z', complete: false } : {}) }))
}
export function bankReview(item: BankTransaction, records: readonly BankTransaction[]): BankReview {
  if (item.sourceCategory === 'transfer') return (item.id === sampleTransfer.debitId || item.id === sampleTransfer.creditId) && records.some(record => record.id === sampleTransfer.debitId) && records.some(record => record.id === sampleTransfer.creditId) ? 'confirmed' : 'needs-review'
  return item.sourceCategory === 'unresolved' ? 'needs-review' : 'recorded'
}
export function bankTotals(records: readonly BankTransaction[]) {
  const posted = records.filter(item => item.status === 'posted')
  const pending = records.filter(item => item.status === 'pending')
  return { credits: sum(posted.filter(item => item.direction === 'credit').map(item => item.amount)), debits: sum(posted.filter(item => item.direction === 'debit').map(item => item.amount)), posted: posted.length, pending: pending.length,
    pendingCredits: sum(pending.filter(item => item.direction === 'credit').map(item => item.amount)), pendingDebits: sum(pending.filter(item => item.direction === 'debit').map(item => item.amount)) }
}
export function bankReconciliation(snapshot: BankSnapshot, records: readonly BankTransaction[]) {
  const totals = bankTotals(records.filter(item => item.accountId === snapshot.accountId))
  const calculated: Money = { currency: 'INR', minor: snapshot.opening.minor + totals.credits.minor - totals.debits.minor }
  return { calculated, difference: snapshot.balance === null ? null : { ...calculated, minor: snapshot.balance.minor - calculated.minor } }
}
export interface BankingFilters { query: string; account: BankId | ''; from: string; to: string; direction: '' | BankTransaction['direction']; status: '' | BankTransaction['status']; category: BankCategory | ''; review: BankReview | '' }
export interface BankingControls { filters: BankingFilters; sort: 'date' | 'amount' | 'description'; direction: 'asc' | 'desc' }
export const defaultBankingFilters: BankingFilters = { query: '', account: '', ...BANK_PERIOD, direction: '', status: '', category: '', review: '' }
export const defaultBankingControls: BankingControls = { filters: defaultBankingFilters, sort: 'date', direction: 'desc' }
export function validBankDates(filters: BankingFilters) {
  const valid = (date: string) => !date || (/^\d{4}-\d{2}-\d{2}$/.test(date) && Number.isFinite(Date.parse(`${date}T00:00:00Z`)) && new Date(`${date}T00:00:00Z`).toISOString().slice(0, 10) === date)
  return valid(filters.from) && valid(filters.to) && (!filters.from || !filters.to || filters.from <= filters.to)
}
export function bankScope(records: readonly BankTransaction[], filters: BankingFilters) {
  if (!validBankDates(filters)) return []
  return records.filter(item => (!filters.account || item.accountId === filters.account) && (!filters.from || item.date >= filters.from) && (!filters.to || item.date <= filters.to))
}
export function selectBankTransactions(records: readonly BankTransaction[], controls: BankingControls, classification = { category: (item: BankTransaction) => item.sourceCategory, review: (item: BankTransaction) => bankReview(item, records) }) {
  const f = controls.filters; const query = f.query.trim().toLocaleLowerCase('en')
  return bankScope(records, f).filter(item => (!query || `${item.description} ${item.counterparty} ${item.reference}`.toLocaleLowerCase('en').includes(query)) && (!f.direction || item.direction === f.direction) && (!f.status || item.status === f.status) && (!f.category || classification.category(item) === f.category) && (!f.review || classification.review(item) === f.review))
    .sort((a, b) => { const comparison = controls.sort === 'amount' ? a.amount.minor < b.amount.minor ? -1 : a.amount.minor > b.amount.minor ? 1 : 0 : controls.sort === 'description' ? a.description.localeCompare(b.description, 'en') : a.date.localeCompare(b.date); return comparison * (controls.direction === 'asc' ? 1 : -1) || a.id.localeCompare(b.id) })
}
