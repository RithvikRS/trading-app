import { id, object, page } from './investments'
import type { Page } from './investments'
import type { SavedReceipt } from './receipt-evidence'

function invalid(): never { throw new Error('Invalid historical comparison') }
const integer = (value: unknown, min: number, max: number): number => typeof value === 'number' && Number.isSafeInteger(value) && value >= min && value <= max ? value : invalid()
const member = <T extends string>(value: unknown, allowed: readonly T[]): T => typeof value === 'string' && allowed.includes(value as T) ? value as T : invalid()
const nullable = <T,>(value: unknown, parse: (value: unknown) => T): T | null => value === null ? null : parse(value)
function keys(value: Record<string, unknown>, allowed: readonly string[]) { if (Object.keys(value).some(key => !allowed.includes(key))) invalid() }
function date(value: unknown): string {
  if (typeof value !== 'string' || !/^(?!0000)\d{4}-\d{2}-\d{2}$/.test(value) || !Number.isFinite(Date.parse(value)) || new Date(value).toISOString().slice(0, 10) !== value) invalid()
  return value
}
export type NativeScope = {
  id: string; receipt_id: string; kind: 'cash' | 'units'; account_id: string; position_id: string | null; currency: 'INR' | 'USD' | null
  period_start: string; period_end: string; date_basis: 'booking' | 'value' | 'settlement' | 'trade'; rule_version: 1; input_count: number
}
export function nativeScope(value: unknown, receiptId: string): NativeScope {
  const raw = object(value); keys(raw, ['id', 'receipt_id', 'kind', 'account_id', 'position_id', 'currency', 'period_start', 'period_end', 'date_basis', 'rule_version', 'input_count'])
  const scope = { id: id(raw.id), receipt_id: id(raw.receipt_id), kind: member(raw.kind, ['cash', 'units'] as const), account_id: id(raw.account_id), position_id: nullable(raw.position_id, id), currency: nullable(raw.currency, value => member(value, ['INR', 'USD'] as const)), period_start: date(raw.period_start), period_end: date(raw.period_end), date_basis: member(raw.date_basis, ['booking', 'value', 'settlement', 'trade'] as const), rule_version: integer(raw.rule_version, 1, 1) as 1, input_count: integer(raw.input_count, 4, 1000) }
  if (scope.receipt_id !== receiptId || scope.period_start > scope.period_end
    || (scope.kind === 'cash' ? scope.currency === null || scope.position_id !== null : scope.currency !== null || scope.position_id === null)
    || (scope.kind === 'units') !== (scope.date_basis === 'trade')) invalid()
  return scope
}
export type ScopePage = Page<NativeScope> & { count: number }
export function scopePage(value: unknown, receipt: SavedReceipt, after: string | null = null, preceding = 0): ScopePage {
  keys(object(value), ['items', 'next_after'])
  if (receipt.mode !== 'reconciled' || receipt.coverage !== 'complete_activity' || integer(receipt.scope_count, 1, 100) <= integer(preceding, 0, 99)
    || preceding % 25 !== 0 || (after === null) !== (preceding === 0)) invalid()
  const result = page(value, item => nativeScope(item, receipt.id), after), count = preceding + result.items.length
  if (count > receipt.scope_count || (result.next_after === null ? count !== receipt.scope_count : count >= receipt.scope_count)) invalid()
  return { ...result, count }
}
export type ComparisonSide = { outcome: 'balanced'; opening: string; closing: string; posted_total: string; calculated_closing: string; difference: string; posted_count: number; pending_count: number }
export type NativeComparison = { scope: NativeScope; source: ComparisonSide; combined: ComparisonSide }
// Exact scaled integers are used only to verify the returned equation. Original lexemes remain the display values.
function decimal(value: unknown, kind: NativeScope['kind'], derived: boolean): { source: string; scaled: bigint } {
  const scale = kind === 'cash' ? 2 : 12
  if (typeof value !== 'string' || value.length > (derived ? 36 : 32) || !/^-?(?:0|[1-9]\d*)(?:\.\d+)?$/.test(value)) invalid()
  const [whole, fraction = ''] = value.replace('-', '').split('.')
  if (fraction.length > scale) invalid()
  const magnitude = BigInt(whole! + fraction.padEnd(scale, '0'))
  if (magnitude >= 10n ** BigInt((derived ? 22 : 18) + scale)) invalid()
  return { source: value, scaled: value.startsWith('-') ? -magnitude : magnitude }
}
function side(value: unknown, scope: NativeScope): ComparisonSide {
  const raw = object(value); keys(raw, ['outcome', 'opening', 'closing', 'posted_total', 'calculated_closing', 'difference', 'posted_count', 'pending_count'])
  if (raw.outcome !== 'balanced') invalid()
  const opening = decimal(raw.opening, scope.kind, false), closing = decimal(raw.closing, scope.kind, false)
  const posted = decimal(raw.posted_total, scope.kind, true), calculated = decimal(raw.calculated_closing, scope.kind, true), difference = decimal(raw.difference, scope.kind, true)
  if (scope.kind === 'units' && (opening.scaled < 0n || closing.scaled < 0n) || opening.scaled + posted.scaled !== closing.scaled || calculated.scaled !== closing.scaled || difference.scaled !== 0n) invalid()
  return { outcome: 'balanced', opening: opening.source, closing: closing.source, posted_total: posted.source, calculated_closing: calculated.source, difference: difference.source, posted_count: integer(raw.posted_count, 0, 1000), pending_count: integer(raw.pending_count, 0, 1000) }
}
export function nativeComparison(value: unknown, selected: NativeScope, receipt: SavedReceipt): NativeComparison {
  if (selected.receipt_id !== receipt.id || receipt.mode !== 'reconciled' || receipt.coverage !== 'complete_activity') invalid()
  const raw = object(value); keys(raw, ['scope', 'source', 'combined'])
  const scope = nativeScope(raw.scope, selected.receipt_id)
  if ((Object.keys(scope) as (keyof NativeScope)[]).some(key => scope[key] !== selected[key])) invalid()
  const source = side(raw.source, scope), combined = side(raw.combined, scope)
  if (decimal(source.opening, scope.kind, false).scaled !== decimal(combined.opening, scope.kind, false).scaled
    || decimal(source.closing, scope.kind, false).scaled !== decimal(combined.closing, scope.kind, false).scaled
    || source.posted_count + source.pending_count + 2 > integer(receipt.row_count, 1, 100)
    || scope.input_count !== 4 + source.posted_count + source.pending_count + combined.posted_count + combined.pending_count) invalid()
  return { scope, source, combined }
}
