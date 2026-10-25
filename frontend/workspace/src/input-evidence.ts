import { id, object, page } from './investments'
import type { Page } from './investments'
import { nativeComparison } from './comparison-evidence'
import type { NativeComparison } from './comparison-evidence'
import type { ReceiptContext, SavedReceipt } from './receipt-evidence'

function invalid(): never { throw new Error('Invalid frozen comparison input') }
const integer = (value: unknown, min = 0, max = Number.MAX_SAFE_INTEGER): number => typeof value === 'number' && Number.isSafeInteger(value) && value >= min && value <= max ? value : invalid()
const member = <T extends string>(value: unknown, choices: readonly T[]): T => typeof value === 'string' && choices.includes(value as T) ? value as T : invalid()
const nullable = <T,>(value: unknown, parse: (value: unknown) => T): T | null => value === null ? null : parse(value)
function keys(value: Record<string, unknown>, allowed: readonly string[]) { if (Object.keys(value).some(key => !allowed.includes(key))) invalid() }
function date(value: unknown): string {
  if (typeof value !== 'string' || !/^(?!0000)\d{4}-\d{2}-\d{2}$/.test(value) || !Number.isFinite(Date.parse(value)) || new Date(value).toISOString().slice(0, 10) !== value) invalid()
  return value
}
export type InputSide = 'source' | 'combined'
export type InputPart = 'opening' | 'activity' | 'closing'
export type InputSelection = Readonly<{ side: InputSide; part: InputPart }>
export type FrozenInput = { id: string; scope_id: string; side: InputSide; part: InputPart; reference_revision: number; source_row_id: string | null; event_id: string | null; snapshot_id: string | null; source: string; evidence_date: string | null; posting_state: 'posted' | 'pending' | null; kind: 'cash' | 'units'; currency: 'INR' | 'USD' | null }
export function frozenInput(value: unknown, comparison: NativeComparison, selection: InputSelection, context: ReceiptContext): FrozenInput {
  const raw = object(value); keys(raw, ['id', 'scope_id', 'side', 'part', 'reference_revision', 'source_row_id', 'event_id', 'snapshot_id', 'source', 'evidence_date', 'posting_state', 'kind', 'currency'])
  const row = { id: id(raw.id), scope_id: id(raw.scope_id), side: member(raw.side, ['source', 'combined'] as const), part: member(raw.part, ['opening', 'activity', 'closing'] as const), reference_revision: integer(raw.reference_revision, 1), source_row_id: nullable(raw.source_row_id, id), event_id: nullable(raw.event_id, id), snapshot_id: nullable(raw.snapshot_id, id), source: raw.source, evidence_date: nullable(raw.evidence_date, date), posting_state: nullable(raw.posting_state, value => member(value, ['posted', 'pending'] as const)), kind: member(raw.kind, ['cash', 'units'] as const), currency: nullable(raw.currency, value => member(value, ['INR', 'USD'] as const)) }
  const scope = comparison.scope
  if (row.scope_id !== scope.id || row.side !== selection.side || row.part !== selection.part || row.kind !== scope.kind || row.currency !== scope.currency) invalid()
  if (typeof row.source !== 'string' || row.source.length > 32 || !/^-?(?:0|[1-9]\d{0,17})(?:\.\d{1,12})?$/.test(row.source) || (row.source.split('.')[1]?.length ?? 0) > (scope.kind === 'cash' ? 2 : 12)) invalid()
  if (row.part === 'activity') {
    if (row.posting_state === null || row.posting_state === 'posted' && row.evidence_date === null || row.evidence_date !== null && (row.evidence_date < scope.period_start || row.evidence_date > scope.period_end)) invalid()
  } else if (row.posting_state !== null || row.evidence_date !== (row.part === 'opening' ? scope.period_start : scope.period_end) || row.source !== comparison[row.side][row.part]
    || row.kind === 'units' && row.source.startsWith('-') && /[1-9]/.test(row.source)) invalid()
  if (row.side === 'source') {
    if (row.source_row_id !== row.id || row.event_id !== null || row.snapshot_id !== null) invalid()
    if (row.id === context.source_row_id && (row.reference_revision !== context.source_review_revision || context.kind !== 'event' || row.part !== 'activity')) invalid()
  } else if (row.part === 'activity') {
    if (row.event_id !== row.id || row.source_row_id !== null || row.snapshot_id !== null) invalid()
    if (context.kind === 'event' && row.id === context.id && row.reference_revision !== context.revision) invalid()
  } else if (row.snapshot_id !== row.id || row.source_row_id !== null || row.event_id !== null) invalid()
  return { ...row, source: row.source }
}
export type InputProgress = Readonly<{ count: number; posted: number; pending: number }>
export const emptyInputProgress: InputProgress = Object.freeze({ count: 0, posted: 0, pending: 0 })
export type InputPage = Page<FrozenInput> & { progress: InputProgress }
export function inputPage(value: unknown, comparison: NativeComparison, receipt: SavedReceipt, context: ReceiptContext, selection: InputSelection, after: string | null = null, preceding: InputProgress = emptyInputProgress): InputPage {
  keys(object(value), ['items', 'next_after'])
  const selected = { side: member(selection.side, ['source', 'combined'] as const), part: member(selection.part, ['opening', 'activity', 'closing'] as const) }
  const valid = nativeComparison(comparison, comparison.scope, receipt), counts = valid[selected.side], activity = selected.part === 'activity'
  const expected = activity ? counts.posted_count + counts.pending_count : 1
  if (receipt.batch_id !== context.batch_id || receipt.coverage !== context.coverage || integer(preceding.count, 0, expected) % 25 !== 0
    || integer(preceding.posted, 0, activity ? counts.posted_count : 0) + integer(preceding.pending, 0, activity ? counts.pending_count : 0) !== (activity ? preceding.count : 0)
    || (after === null) !== (preceding.count === 0) || after !== null && preceding.count >= expected) invalid()
  const result = page(value, item => frozenInput(item, valid, selected, context), after)
  const progress = { count: preceding.count + result.items.length, posted: preceding.posted + result.items.filter(item => item.posting_state === 'posted').length, pending: preceding.pending + result.items.filter(item => item.posting_state === 'pending').length }
  if (progress.count > expected || progress.posted > (activity ? counts.posted_count : 0) || progress.pending > (activity ? counts.pending_count : 0)
    || (result.next_after === null ? progress.count !== expected || activity && (progress.posted !== counts.posted_count || progress.pending !== counts.pending_count) : progress.count >= expected)) invalid()
  return { ...result, progress }
}
