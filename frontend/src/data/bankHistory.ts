import { money } from './money'
import type { BankCategory, BankId, BankSnapshot, BankTransaction } from './banking'

// Fixed fictional statements. Balances are independent evidence, not calculated fixtures.
function record(id: string, accountId: BankId, date: string, direction: 'credit' | 'debit', amount: string, description: string, counterparty: string, sourceCategory: BankCategory): BankTransaction {
  return { id, accountId, ownerId: 'sample-owner', sourceId: `sample-${accountId}-${date.slice(5, 7) === '08' ? 'aug' : 'sep'}`, date, direction, amount: money(amount), status: 'posted', description, counterparty, sourceCategory,
    narration: `FICTIONAL RECORD / ${description} / INR ${amount} / ${direction.toUpperCase()}`, reference: `Sample reference ${id.slice(1)}` }
}
export const historicalTransactions: readonly BankTransaction[] = [
  record('t29', 'hdfc', '2026-08-01', 'credit', '90000', 'August salary', 'Sample employer', 'salary'),
  record('t30', 'hdfc', '2026-08-02', 'debit', '22000', 'August rent', 'Sample home', 'housing'),
  record('t31', 'hdfc', '2026-08-03', 'debit', '1700', 'August electricity', 'Sample utilities', 'utilities'),
  record('t32', 'hdfc', '2026-08-06', 'debit', '4000', 'August groceries', 'Sample market', 'groceries'),
  record('t33', 'hdfc', '2026-08-12', 'debit', '6000', 'August home purchase', 'Sample store', 'shopping'),
  record('t34', 'hdfc', '2026-08-16', 'debit', '900', 'August evening meal', 'Sample kitchen', 'dining'),
  record('t35', 'hdfc', '2026-08-09', 'debit', '12000', 'August investment funding', 'Sample investment account', 'investment'),
  record('t36', 'hdfc', '2026-08-28', 'debit', '1800', 'August grocery top-up', 'Sample market', 'groceries'),
  record('t37', 'sbi', '2026-08-01', 'credit', '230', 'August interest', 'Sample bank interest', 'interest'),
  record('t38', 'sbi', '2026-08-03', 'debit', '1200', 'August broadband', 'Sample broadband', 'utilities'),
  record('t39', 'sbi', '2026-08-15', 'debit', '499', 'August subscription', 'Sample subscription', 'subscriptions'),
  record('t40', 'sbi', '2026-08-16', 'debit', '900', 'August pharmacy', 'Sample pharmacy', 'health'),
  record('t41', 'sbi', '2026-08-19', 'debit', '2000', 'August maintenance', 'Sample services', 'utilities'),
  record('t42', 'sbi', '2026-08-22', 'debit', '5.90', 'August service fee', 'Sample bank fee', 'fee'),
  record('t43', 'sbi', '2026-08-24', 'credit', '5000', 'August investment withdrawal', 'Sample investment account', 'investment'),
  record('t44', 'hdfc', '2026-09-01', 'credit', '95000', 'September salary', 'Sample employer', 'salary'),
  record('t45', 'hdfc', '2026-09-02', 'debit', '22000', 'September rent', 'Sample home', 'housing'),
  record('t46', 'hdfc', '2026-09-03', 'debit', '1900', 'September electricity', 'Sample utilities', 'utilities'),
  record('t47', 'hdfc', '2026-09-06', 'debit', '4500', 'September groceries', 'Sample market', 'groceries'),
  record('t48', 'hdfc', '2026-09-16', 'debit', '1100', 'September evening meal', 'Sample kitchen', 'dining'),
  record('t49', 'hdfc', '2026-09-09', 'debit', '15000', 'September investment funding', 'Sample investment account', 'investment'),
  record('t50', 'hdfc', '2026-09-26', 'debit', '2200', 'September grocery top-up', 'Sample market', 'groceries'),
  record('t51', 'hdfc', '2026-09-05', 'credit', '1500', 'Refund of August purchase', 'Sample store', 'refund'),
  record('t52', 'hdfc', '2026-09-12', 'debit', '2000', 'September home purchase', 'Sample store', 'shopping'),
  record('t53', 'sbi', '2026-09-01', 'credit', '240', 'September interest', 'Sample bank interest', 'interest'),
  record('t54', 'sbi', '2026-09-03', 'debit', '1200', 'September broadband', 'Sample broadband', 'utilities'),
  record('t55', 'sbi', '2026-09-15', 'debit', '499', 'September subscription', 'Sample subscription', 'subscriptions'),
  record('t56', 'sbi', '2026-09-16', 'debit', '1200', 'September pharmacy', 'Sample pharmacy', 'health'),
  record('t57', 'sbi', '2026-09-19', 'debit', '2100', 'September maintenance', 'Sample services', 'utilities'),
  record('t58', 'sbi', '2026-09-22', 'debit', '5.90', 'September service fee', 'Sample bank fee', 'fee'),
]
function statement(accountId: BankId, month: '08' | '09', opening: string, closing: string): BankSnapshot {
  const to = `2026-${month}-${month === '08' ? '31' : '30'}`, timestamp = `${to}T18:29:59Z`
  return { accountId, sourceId: `sample-${accountId}-${month === '08' ? 'aug' : 'sep'}`, from: `2026-${month}-01`, to,
    opening: money(opening), balance: money(closing), balanceDate: timestamp, activityDate: timestamp, complete: true }
}
export const historicalSnapshots: readonly BankSnapshot[] = [
  statement('hdfc', '08', '87885.90', '129485.90'), statement('sbi', '08', '42338.80', '42963.90'),
  statement('hdfc', '09', '129485.90', '177285.90'), statement('sbi', '09', '42963.90', '38199'),
]
