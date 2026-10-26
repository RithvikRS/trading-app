import { component, id, object, page, sourceObservation } from './investments'
import type { Component, Page, Position, SourceObservation } from './investments'

function invalid(): never { throw new Error('Invalid account activity evidence') }
const nullable = <T,>(value: unknown, parse: (value: unknown) => T): T | null => value === null ? null : parse(value)
const member = <T extends string>(value: unknown, allowed: readonly T[]): T => typeof value === 'string' && allowed.includes(value as T) ? value as T : invalid()
const revision = (value: unknown): number => typeof value === 'number' && Number.isSafeInteger(value) && value > 0 ? value : invalid()
const boolean = (value: unknown): boolean => typeof value === 'boolean' ? value : invalid()
const date = (value: unknown): string => typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value) && !value.startsWith('0000-') && Number.isFinite(Date.parse(value)) && new Date(value).toISOString().slice(0, 10) === value ? value : invalid()
function keys(value: Record<string, unknown>, allowed: readonly string[]) { if (Object.keys(value).some(key => !allowed.includes(key))) invalid() }
const kinds = ['buy', 'sell', 'subscription', 'redemption', 'dividend', 'fee', 'withholding', 'cash_movement'] as const
const tradeKinds = ['buy', 'sell', 'subscription', 'redemption'] as const
const trades = (kind: string) => (tradeKinds as readonly string[]).includes(kind)
export const eventRoles = {
  buy: ['quantity', 'net_cash', 'gross_cash', 'unit_price', 'fee', 'withholding'],
  sell: ['quantity', 'net_cash', 'gross_cash', 'unit_price', 'fee', 'withholding'],
  subscription: ['quantity', 'net_cash', 'gross_cash', 'unit_price', 'fee', 'withholding'],
  redemption: ['quantity', 'net_cash', 'gross_cash', 'unit_price', 'fee', 'withholding'],
  dividend: ['net_cash', 'gross_cash', 'fee', 'withholding'],
  fee: ['net_cash'], withholding: ['net_cash'], cash_movement: ['net_cash', 'fee', 'withholding'],
} as const
export type EventEvidence = {
  id: string; account_id: string; position_id: string | null; instrument_id: string | null
  kind: typeof kinds[number]; revision: number; is_current: boolean; account_state: 'active' | 'archived'
  status: 'active' | 'cancelled'; posting_state: 'posted' | 'pending'
  correction_reason: 'source_correction' | 'posting_update' | 'cancellation' | 'reinstatement' | null
  trade_date: string | null; settlement_date: string | null; booking_date: string | null; value_date: string | null
  source_row_id: string; source_review_revision: number; source_id: string; observation_id: string; batch_id: string
  coverage: 'snapshot' | 'partial_activity' | 'complete_activity' | 'unknown'
  period_start: string | null; period_end: string | null; cash_date_basis: 'booking' | 'value' | 'settlement' | null
  components: Component[]
}
export type EventIdentity = Pick<EventEvidence, 'id' | 'account_id' | 'position_id' | 'instrument_id' | 'kind' | 'revision'>
export function eventIdentity(item: EventEvidence): EventIdentity { return { id: item.id, account_id: item.account_id, position_id: item.position_id, instrument_id: item.instrument_id, kind: item.kind, revision: item.revision } }
export function eventEvidence(value: unknown, accountId: string): EventEvidence {
  const raw = object(value)
  keys(raw, ['id', 'account_id', 'position_id', 'instrument_id', 'kind', 'revision', 'is_current', 'account_state', 'status', 'posting_state', 'correction_reason', 'trade_date', 'settlement_date', 'booking_date', 'value_date', 'source_row_id', 'source_review_revision', 'source_id', 'observation_id', 'batch_id', 'coverage', 'period_start', 'period_end', 'cash_date_basis', 'components'])
  const result = {
    id: id(raw.id), account_id: id(raw.account_id), position_id: nullable(raw.position_id, id), instrument_id: nullable(raw.instrument_id, id), kind: member(raw.kind, kinds),
    revision: revision(raw.revision), is_current: boolean(raw.is_current), account_state: member(raw.account_state, ['active', 'archived'] as const),
    status: member(raw.status, ['active', 'cancelled'] as const), posting_state: member(raw.posting_state, ['posted', 'pending'] as const),
    correction_reason: nullable(raw.correction_reason, value => member(value, ['source_correction', 'posting_update', 'cancellation', 'reinstatement'] as const)),
    trade_date: nullable(raw.trade_date, date), settlement_date: nullable(raw.settlement_date, date), booking_date: nullable(raw.booking_date, date), value_date: nullable(raw.value_date, date),
    source_row_id: id(raw.source_row_id), source_review_revision: revision(raw.source_review_revision), source_id: id(raw.source_id), observation_id: id(raw.observation_id), batch_id: id(raw.batch_id),
    coverage: member(raw.coverage, ['snapshot', 'partial_activity', 'complete_activity', 'unknown'] as const),
    period_start: nullable(raw.period_start, date), period_end: nullable(raw.period_end, date), cash_date_basis: nullable(raw.cash_date_basis, value => member(value, ['booking', 'value', 'settlement'] as const)), components: [] as Component[],
  }
  if (result.account_id !== accountId || (result.position_id === null) !== (result.instrument_id === null)
    || (trades(result.kind) || result.kind === 'dividend') && result.position_id === null
    || (result.period_start === null) !== (result.period_end === null)
    || result.coverage !== 'unknown' && result.period_start === null
    || result.period_start !== null && result.period_end !== null && result.period_start > result.period_end
    || (result.revision === 1) !== (result.correction_reason === null)
    || (result.status === 'cancelled') !== (result.correction_reason === 'cancellation')
    || result.correction_reason === 'posting_update' && result.posting_state !== 'posted'
    || !Array.isArray(raw.components) || raw.components.length > 8) invalid()
  result.components = raw.components.map(value => {
    const raw = object(value); keys(raw, ['role', 'source', 'currency', 'missing_reason'])
    const parsed = component(raw)
    if (!(eventRoles[result.kind] as readonly string[]).includes(parsed.role)) invalid()
    return parsed
  })
  if (new Set(result.components.map(item => item.role)).size !== result.components.length) invalid()
  if (result.status === 'cancelled') {
    if (result.components.length || result.booking_date === null) invalid()
  } else {
    const cash = result.components.find(item => item.role === 'net_cash'), quantity = result.components.find(item => item.role === 'quantity')
    if (!cash || cash.source === null || result.components.some(item => item.currency !== null && item.currency !== cash.currency)
      || trades(result.kind) && (result.trade_date === null || !quantity || quantity.source === null)
      || !trades(result.kind) && result.booking_date === null) invalid()
    const sign = (source: string): number => /^-?0(?:\.0+)?$/.test(source) ? 0 : source.startsWith('-') ? -1 : 1
    const buying = result.kind === 'buy' || result.kind === 'subscription', selling = result.kind === 'sell' || result.kind === 'redemption'
    if (buying && (sign(cash.source) !== -1 || sign(quantity!.source!) !== 1)
      || selling && (sign(cash.source) !== 1 || sign(quantity!.source!) !== -1)
      || result.kind === 'dividend' && sign(cash.source) < 0
      || ['fee', 'withholding'].includes(result.kind) && sign(cash.source) > 0
      || result.components.some(item => item.role === 'unit_price' && item.source !== null && sign(item.source) <= 0)) invalid()
  }
  return result
}
export function accountActivityPage(value: unknown, accountId: string, after: string | null = null): Page<EventEvidence> {
  keys(object(value), ['items', 'next_after'])
  return page(value, value => { const item = eventEvidence(value, accountId); if (!item.is_current) invalid(); return item }, after)
}
export function activityPage(value: unknown, position: Position, after: string | null = null): Page<EventEvidence> {
  const result = accountActivityPage(value, position.account_id, after)
  if (result.items.some(item => item.position_id === position.id && item.instrument_id !== position.instrument_id)) invalid()
  return result
}
export type ActivityHistory = { items: EventEvidence[]; next_before: number | null }
export function activityHistory(value: unknown, root: EventIdentity, before: number | null = null): ActivityHistory {
  const raw = object(value); keys(raw, ['items', 'next_before'])
  if (!Array.isArray(raw.items) || raw.items.length > 25) invalid()
  const items = raw.items.map(value => eventEvidence(value, root.account_id)), next = nullable(raw.next_before, revision)
  let previous = before
  items.forEach((item, index) => {
    if (item.id !== root.id || item.position_id !== root.position_id || item.instrument_id !== root.instrument_id || item.kind !== root.kind
      || before === null && index === 0 && item.revision < root.revision
      || previous !== null && item.revision >= previous || item.is_current !== (before === null && index === 0)) invalid()
    previous = item.revision
  })
  if (next !== null && (items.length !== 25 || next !== previous || next === 1)) invalid()
  return { items, next_before: next }
}
export function activityCoveragePage(value: unknown, sourceId: string, after: string | null = null): Page<SourceObservation> {
  keys(object(value), ['items', 'next_after'])
  return page(value, value => {
    const raw = object(value); keys(raw, ['id', 'source_id', 'previous_id', 'is_current', 'coverage', 'period_start', 'period_end'])
    const item = sourceObservation(raw)
    if (item.source_id !== sourceId) invalid()
    if (item.period_start !== null) date(item.period_start)
    if (item.period_end !== null) date(item.period_end)
    return item
  }, after)
}
