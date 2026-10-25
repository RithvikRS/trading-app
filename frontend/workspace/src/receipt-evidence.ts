import { id, object, page } from './investments'
import type { Page } from './investments'

function invalid(): never { throw new Error('Invalid saved completion evidence') }
const integer = (value: unknown, min = 1, max = Number.MAX_SAFE_INTEGER): number => typeof value === 'number' && Number.isSafeInteger(value) && value >= min && value <= max ? value : invalid()
const nullable = <T,>(value: unknown, parse: (value: unknown) => T): T | null => value === null ? null : parse(value)
const member = <T extends string>(value: unknown, allowed: readonly T[]): T => typeof value === 'string' && allowed.includes(value as T) ? value as T : invalid()
function keys(value: Record<string, unknown>, allowed: readonly string[]) { if (Object.keys(value).some(key => !allowed.includes(key))) invalid() }
function instant(value: unknown): string {
  if (typeof value !== 'string' || value.length > 32 || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$/.test(value) || value.startsWith('0000-')) invalid()
  const date = value.slice(0, 10), offset = value.endsWith('Z') ? 'Z' : value.slice(-6)
  if (!Number.isFinite(Date.parse(date)) || new Date(date).toISOString().slice(0, 10) !== date || Number(value.slice(11, 13)) > 23 || Number(value.slice(14, 16)) > 59 || Number(value.slice(17, 19)) > 59
    || offset !== 'Z' && (offset === '-00:00' || Number(offset.slice(4)) > 59 || Number(offset.slice(1, 3)) > 14 || Number(offset.slice(1, 3)) === 14 && Number(offset.slice(4)) !== 0)
    || !Number.isFinite(Date.parse(value)) || !/^(?!0000)\d{4}-/.test(new Date(value).toISOString())) invalid()
  return value
}
export type ReceiptContext = { kind: 'event' | 'lot'; id: string; revision: number; batch_id: string; source_row_id: string; source_review_revision: number; coverage: 'snapshot' | 'partial_activity' | 'complete_activity' | 'unknown' }
export function receiptContext(kind: ReceiptContext['kind'], value: Omit<ReceiptContext, 'kind'>): ReceiptContext {
  return { kind, id: value.id, revision: value.revision, batch_id: value.batch_id, source_row_id: value.source_row_id, source_review_revision: value.source_review_revision, coverage: value.coverage }
}
export type SavedReceipt = { id: string; batch_id: string; batch_revision: number; mode: 'limited' | 'reconciled'; coverage: 'snapshot' | 'partial_activity' | 'complete_activity' | 'unknown'; created_at: string; row_count: number; selection_count: number; scope_count: number }
export function savedReceipt(value: unknown, context: Pick<ReceiptContext, 'batch_id' | 'coverage'>): SavedReceipt {
  const raw = object(value); keys(raw, ['id', 'batch_id', 'batch_revision', 'mode', 'coverage', 'created_at', 'row_count', 'selection_count', 'scope_count'])
  const result = { id: id(raw.id), batch_id: id(raw.batch_id), batch_revision: integer(raw.batch_revision), mode: member(raw.mode, ['limited', 'reconciled'] as const), coverage: member(raw.coverage, ['snapshot', 'partial_activity', 'complete_activity', 'unknown'] as const), created_at: instant(raw.created_at), row_count: integer(raw.row_count, 1, 100), selection_count: integer(raw.selection_count, 0, 100), scope_count: integer(raw.scope_count, 0, 100) }
  if (result.batch_id !== context.batch_id || result.coverage !== context.coverage || result.selection_count > result.row_count || (result.mode === 'reconciled') !== (result.coverage === 'complete_activity') || (result.mode === 'reconciled') !== (result.scope_count > 0)) invalid()
  return result
}
export function receiptPage(value: unknown, context: ReceiptContext, after: string | null = null): Page<SavedReceipt> {
  keys(object(value), ['items', 'next_after'])
  return page(value, item => savedReceipt(item, context), after)
}
export type CompletedRow = { id: string; receipt_id: string; review_revision: number; operation: 'record' | 'correct' | 'exclude'; outcome: 'recorded' | 'linked' | 'corrected' | 'excluded'; event_id: string | null; lot_observation_id: string | null; snapshot_id: string | null; record_revision: number | null; provider_identity_id: string | null; selection_id: string | null; selection_revision: number | null }
export function completedRow(value: unknown, receiptId: string, context: ReceiptContext): CompletedRow {
  const raw = object(value); keys(raw, ['id', 'receipt_id', 'review_revision', 'operation', 'outcome', 'event_id', 'lot_observation_id', 'snapshot_id', 'record_revision', 'provider_identity_id', 'selection_id', 'selection_revision'])
  const result = { id: id(raw.id), receipt_id: id(raw.receipt_id), review_revision: integer(raw.review_revision), operation: member(raw.operation, ['record', 'correct', 'exclude'] as const), outcome: member(raw.outcome, ['recorded', 'linked', 'corrected', 'excluded'] as const), event_id: nullable(raw.event_id, id), lot_observation_id: nullable(raw.lot_observation_id, id), snapshot_id: nullable(raw.snapshot_id, id), record_revision: nullable(raw.record_revision, value => integer(value)), provider_identity_id: nullable(raw.provider_identity_id, id), selection_id: nullable(raw.selection_id, id), selection_revision: nullable(raw.selection_revision, value => integer(value)) }
  const targets = [result.event_id, result.lot_observation_id, result.snapshot_id]
  if (result.receipt_id !== receiptId) invalid()
  if (result.operation === 'exclude') {
    if (result.outcome !== 'excluded' || [...targets, result.record_revision, result.provider_identity_id, result.selection_id, result.selection_revision].some(value => value !== null)) invalid()
  } else if (result.record_revision === null || targets.filter(value => value !== null).length !== 1 || result.operation === 'record' && !['recorded', 'linked'].includes(result.outcome) || result.operation === 'correct' && result.outcome !== 'corrected') invalid()
  if (result.provider_identity_id !== null && (result.event_id === null || result.operation !== 'record') || (result.selection_id === null) !== (result.selection_revision === null) || result.selection_id !== null && result.snapshot_id === null) invalid()
  if (result.id === context.source_row_id && (result.review_revision !== context.source_review_revision || result.record_revision !== context.revision || (context.kind === 'event' ? result.event_id : result.lot_observation_id) !== context.id)) invalid()
  return result
}
export type ReceiptProgress = Readonly<{ count: number; selections: number; originSeen: boolean }>
export type CompletedPage = Page<CompletedRow> & { progress: ReceiptProgress }
export const emptyReceiptProgress: ReceiptProgress = Object.freeze({ count: 0, selections: 0, originSeen: false })
export function completedRows(value: unknown, receipt: SavedReceipt, context: ReceiptContext, after: string | null = null, preceding: ReceiptProgress = emptyReceiptProgress): CompletedPage {
  keys(object(value), ['items', 'next_after'])
  if (receipt.batch_id !== context.batch_id || receipt.coverage !== context.coverage || receipt.selection_count > receipt.row_count
    || integer(preceding.count, 0, 100) >= receipt.row_count || integer(preceding.selections, 0, preceding.count) > receipt.selection_count
    || typeof preceding.originSeen !== 'boolean' || (after === null) !== (preceding.count === 0) || preceding.count % 25 !== 0
    || preceding.count === 0 && preceding.originSeen) invalid()
  const result = page(value, item => completedRow(item, receipt.id, context), after)
  const progress = { count: preceding.count + result.items.length, selections: preceding.selections + result.items.filter(item => item.selection_id !== null).length, originSeen: preceding.originSeen || result.items.some(item => item.id === context.source_row_id) }
  if (progress.count > receipt.row_count || progress.selections > receipt.selection_count
    || (result.next_after === null ? progress.count !== receipt.row_count || progress.selections !== receipt.selection_count || !progress.originSeen : progress.count >= receipt.row_count)) invalid()
  return { ...result, progress }
}