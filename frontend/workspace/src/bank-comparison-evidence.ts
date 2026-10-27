import { bankAccount } from './banking-evidence'
import type { BankProvenance } from './bank-provenance'
import { nativeComparison, nativeScope, scopePage } from './comparison-evidence'
import type { NativeComparison, NativeScope, ScopePage } from './comparison-evidence'
import { savedReceipt } from './receipt-evidence'
import type { SavedReceipt } from './receipt-evidence'

function invalid(): never { throw new Error('Invalid saved bank comparison') }
const bit = (currency: 'INR' | 'USD') => currency === 'INR' ? 1 : 2
export type BankScopeProgress = Readonly<{ count: number; bankSeen: number }>
export const emptyBankScopeProgress: BankScopeProgress = Object.freeze({ count: 0, bankSeen: 0 })
export type BankScopePage = ScopePage & { progress: BankScopeProgress }
function contextReceipt(context: BankProvenance, value: SavedReceipt): SavedReceipt {
  const account = bankAccount(context.account), origin = context.origin, receipt = savedReceipt(value, origin)
  if (origin.kind !== 'event' || origin.coverage !== 'complete_activity' || origin.status !== 'active'
    || origin.period_start === null || origin.period_end === null || !['booking', 'value', 'settlement'].includes(origin.cash_date_basis ?? '')
    || !['posted', 'pending'].includes(origin.posting_state) || origin.native_currency === null || !account.currencies.includes(origin.native_currency)
    || receipt.mode !== 'reconciled') invalid()
  return receipt
}
function bankScope(value: unknown, receipt: SavedReceipt, context: BankProvenance): NativeScope {
  const scope = nativeScope(value, receipt.id), origin = context.origin
  if (scope.period_start !== origin.period_start || scope.period_end !== origin.period_end
    || scope.kind === 'cash' && scope.date_basis !== origin.cash_date_basis
    || scope.account_id === context.account.id && (scope.kind !== 'cash' || scope.position_id !== null || scope.currency === null || !context.account.currencies.includes(scope.currency))) invalid()
  return scope
}
export function bankScopeEligible(scope: NativeScope, context: BankProvenance): boolean {
  return scope.account_id === context.account.id && scope.kind === 'cash' && scope.position_id === null && scope.currency !== null && context.account.currencies.includes(scope.currency)
}
export function bankScopePage(value: unknown, receiptValue: SavedReceipt, context: BankProvenance, after: string | null = null, preceding: BankScopeProgress = emptyBankScopeProgress): BankScopePage {
  const receipt = contextReceipt(context, receiptValue), allowed = context.account.currencies.reduce((mask, currency) => mask | bit(currency), 0)
  if (!Number.isSafeInteger(preceding.bankSeen) || preceding.bankSeen < 0 || preceding.bankSeen > 3 || (preceding.bankSeen & ~allowed) !== 0
    || preceding.count === 0 && preceding.bankSeen !== 0 || Number(Boolean(preceding.bankSeen & 1)) + Number(Boolean(preceding.bankSeen & 2)) > preceding.count) invalid()
  const result = scopePage(value, receipt, after, preceding.count)
  let bankSeen = preceding.bankSeen
  const items = result.items.map(value => {
    const scope = bankScope(value, receipt, context)
    if (bankScopeEligible(scope, context)) { const flag = bit(scope.currency!); if (bankSeen & flag) invalid(); bankSeen |= flag }
    return scope
  })
  if (result.next_after === null && !(bankSeen & bit(context.origin.native_currency!))) invalid()
  return { ...result, items, progress: { count: result.count, bankSeen } }
}
export function bankComparison(value: unknown, selected: NativeScope, receiptValue: SavedReceipt, context: BankProvenance): NativeComparison {
  const receipt = contextReceipt(context, receiptValue), scope = bankScope(selected, receipt, context)
  if (!bankScopeEligible(scope, context)) invalid()
  const result = nativeComparison(value, scope, receipt)
  if (scope.currency === context.origin.native_currency && (context.origin.posting_state === 'posted' ? result.source.posted_count : result.source.pending_count) < 1) invalid()
  return result
}
