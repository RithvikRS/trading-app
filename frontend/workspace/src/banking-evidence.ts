import { parseAccountPage } from './accounts'
import type { Account, AccountPage } from './accounts'
import { accountActivityPage, activityHistory } from './activity-evidence'
import type { ActivityHistory, EventEvidence, EventIdentity } from './activity-evidence'
import type { Page } from './investments'

function invalid(): never { throw new Error('Invalid saved bank evidence') }
export type BankAccount = Account & { kind: 'bank'; institution: 'hdfc' | 'sbi'; market: 'IN' }
export function bankAccount(value: Account): BankAccount {
  const account = parseAccountPage({ items: [value], next_after: null }, null).items[0]!
  if (account.kind !== 'bank' || !['hdfc', 'sbi'].includes(account.institution) || account.market !== 'IN') invalid()
  return account as BankAccount
}
export function bankAccountPage(value: unknown, after: string | null = null): AccountPage {
  const result = parseAccountPage(value, after)
  for (const account of result.items) if (account.kind === 'bank') bankAccount(account)
  return result
}
function bankEvent(item: EventEvidence, account: BankAccount): EventEvidence {
  if (item.account_id !== account.id || item.position_id !== null || item.instrument_id !== null || !['cash_movement', 'fee', 'withholding'].includes(item.kind)
    || item.components.some(value => value.currency !== null && !account.currencies.includes(value.currency))) invalid()
  return item
}
export function bankActivityPage(value: unknown, selected: BankAccount, after: string | null = null): Page<EventEvidence> {
  const account = bankAccount(selected), result = accountActivityPage(value, account.id, after)
  return { ...result, items: result.items.map(item => bankEvent(item, account)) }
}
export function bankHistory(value: unknown, selected: BankAccount, root: EventIdentity, before: number | null = null): ActivityHistory {
  const account = bankAccount(selected)
  if (root.account_id !== account.id || root.position_id !== null || root.instrument_id !== null) invalid()
  const result = activityHistory(value, root, before)
  if (before === null && !result.items.length) invalid()
  return { ...result, items: result.items.map(item => bankEvent(item, account)) }
}
