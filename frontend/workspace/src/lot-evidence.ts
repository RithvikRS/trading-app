import { component, id, object, page } from './investments'
import type { Component, Page, Position } from './investments'

function invalid(): never { throw new Error('Invalid lot evidence') }
const nullable = <T,>(value: unknown, parse: (value: unknown) => T): T | null => value === null ? null : parse(value)
const member = <T extends string>(value: unknown, allowed: readonly T[]): T => typeof value === 'string' && allowed.includes(value as T) ? value as T : invalid()
const revision = (value: unknown): number => typeof value === 'number' && Number.isSafeInteger(value) && value > 0 ? value : invalid()
const boolean = (value: unknown): boolean => typeof value === 'boolean' ? value : invalid()
const date = (value: unknown): string => typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value) && !value.startsWith('0000-') && Number.isFinite(Date.parse(value)) && new Date(value).toISOString().slice(0, 10) === value ? value : invalid()
function keys(value: Record<string, unknown>, allowed: readonly string[]) { if (Object.keys(value).some(key => !allowed.includes(key))) invalid() }
const states = ['active', 'archived'] as const
const scopes = ['lot_acquisition', 'lot_remaining'] as const
const roles = ['quantity', 'unit_price', 'acquisition_cost', 'discount_amount', 'reported_tax_basis', 'fee', 'withholding'] as const
export type Lot = { id: string; position_id: string; account_id: string; instrument_id: string; account_state: 'active' | 'archived' }
export type LotObservation = Lot & {
  lot_id: string; revision: number; is_current: boolean; scope: typeof scopes[number]
  correction_reason: 'source_correction' | 'cancellation' | 'reinstatement' | null
  status: 'active' | 'cancelled'; components: Component[]
  as_of_date: string | null; acquisition_date: string | null; booking_date: string | null
  source_row_id: string; source_review_revision: number; source_id: string; observation_id: string; batch_id: string
  coverage: 'snapshot' | 'partial_activity' | 'complete_activity' | 'unknown'
  period_start: string | null; period_end: string | null; cash_date_basis: 'booking' | 'value' | 'settlement' | null
}
function identity(value: unknown, position: Pick<Position, 'id' | 'account_id' | 'instrument_id'>): Lot {
  const raw = object(value)
  const result = { id: id(raw.id), position_id: id(raw.position_id), account_id: id(raw.account_id), instrument_id: id(raw.instrument_id), account_state: member(raw.account_state, states) }
  if (result.position_id !== position.id || result.account_id !== position.account_id || result.instrument_id !== position.instrument_id) invalid()
  return result
}
export function lotPage(value: unknown, position: Position, after: string | null = null): Page<Lot> {
  return page(value, item => {
    const raw = object(item); keys(raw, ['id', 'position_id', 'account_id', 'instrument_id', 'account_state'])
    return identity(raw, position)
  }, after)
}
export function lotObservation(value: unknown, lot: Lot): LotObservation {
  const raw = object(value)
  keys(raw, ['id', 'position_id', 'account_id', 'instrument_id', 'account_state', 'lot_id', 'revision', 'is_current', 'scope', 'correction_reason', 'status', 'components', 'as_of_date', 'acquisition_date', 'booking_date', 'source_row_id', 'source_review_revision', 'source_id', 'observation_id', 'batch_id', 'coverage', 'period_start', 'period_end', 'cash_date_basis'])
  const parent = identity(raw, { id: lot.position_id, account_id: lot.account_id, instrument_id: lot.instrument_id })
  const result = {
    ...parent, lot_id: id(raw.lot_id), revision: revision(raw.revision), is_current: boolean(raw.is_current),
    scope: member(raw.scope, scopes), correction_reason: nullable(raw.correction_reason, value => member(value, ['source_correction', 'cancellation', 'reinstatement'] as const)),
    status: member(raw.status, ['active', 'cancelled'] as const), components: [] as Component[],
    as_of_date: nullable(raw.as_of_date, date), acquisition_date: nullable(raw.acquisition_date, date), booking_date: nullable(raw.booking_date, date),
    source_row_id: id(raw.source_row_id), source_review_revision: revision(raw.source_review_revision), source_id: id(raw.source_id), observation_id: id(raw.observation_id), batch_id: id(raw.batch_id),
    coverage: member(raw.coverage, ['snapshot', 'partial_activity', 'complete_activity', 'unknown'] as const),
    period_start: nullable(raw.period_start, date), period_end: nullable(raw.period_end, date),
    cash_date_basis: nullable(raw.cash_date_basis, value => member(value, ['booking', 'value', 'settlement'] as const)),
  }
  if (result.lot_id !== lot.id || !Array.isArray(raw.components) || raw.components.length > roles.length) invalid()
  result.components = raw.components.map(value => {
    const raw = object(value); keys(raw, ['role', 'source', 'currency', 'missing_reason'])
    const parsed = component(raw)
    if (!roles.includes(parsed.role as typeof roles[number])) invalid()
    return parsed
  })
  if (new Set(result.components.map(item => item.role)).size !== result.components.length
    || (result.period_start === null) !== (result.period_end === null)
    || result.coverage !== 'unknown' && result.period_start === null
    || result.period_start !== null && result.period_end !== null && result.period_start > result.period_end
    || result.acquisition_date !== null && result.as_of_date !== null && result.acquisition_date > result.as_of_date
    || (result.revision === 1) !== (result.correction_reason === null)
    || (result.status === 'cancelled') !== (result.correction_reason === 'cancellation')) invalid()
  if (result.status === 'cancelled') {
    if (result.components.length || result.booking_date === null) invalid()
  } else {
    const quantity = result.components.find(item => item.role === 'quantity')?.source
    if (result.as_of_date === null || quantity === undefined || quantity === null) invalid()
    for (const item of result.components) {
      if (item.source === null) continue
      const negative = item.source.startsWith('-') && !/^-0(?:\.0+)?$/.test(item.source)
      const zero = /^-?0(?:\.0+)?$/.test(item.source)
      if (['quantity', 'acquisition_cost', 'discount_amount', 'reported_tax_basis'].includes(item.role) && negative
        || item.role === 'quantity' && result.scope === 'lot_acquisition' && zero
        || item.role === 'unit_price' && (negative || zero)) invalid()
    }
  }
  return result
}
export function observationPage(value: unknown, lot: Lot, after: string | null = null): Page<LotObservation> {
  return page(value, item => { const result = lotObservation(item, lot); if (!result.is_current) invalid(); return result }, after)
}
export type LotHistory = { items: LotObservation[]; next_before: number | null }
export function observationHistory(value: unknown, lot: Lot, root: Pick<LotObservation, 'id' | 'scope' | 'revision'>, before: number | null = null): LotHistory {
  const raw = object(value); keys(raw, ['items', 'next_before'])
  if (!Array.isArray(raw.items) || raw.items.length > 25) invalid()
  const items = raw.items.map(item => lotObservation(item, lot)), next = nullable(raw.next_before, revision)
  let previous = before
  items.forEach((item, index) => {
    if (item.id !== root.id || item.scope !== root.scope || before === null && index === 0 && item.revision < root.revision
      || previous !== null && item.revision >= previous
      || item.is_current !== (before === null && index === 0)) invalid()
    previous = item.revision
  })
  if (next !== null && (items.length !== 25 || next !== previous || next === 1)) invalid()
  return { items, next_before: next }
}
