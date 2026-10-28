// Bounded projections of saved evidence. Decimal lexemes never pass through Number.
export type Json = Record<string, unknown>
export const object = (value: unknown): Json => { if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Invalid financial response'); return value as Json }
const fail = (): never => { throw new Error('Invalid financial response') }
export const text = (value: unknown, max = 120): string => typeof value === 'string' && value.length > 0 && value.length <= max && !/[\u0000-\u001f\u007f]/.test(value) ? value : fail()
export const id = (value: unknown): string => typeof value === 'string' && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(value) && value !== '00000000-0000-0000-0000-000000000000' ? value : fail()
const nullable = <T,>(value: unknown, parse: (value: unknown) => T): T | null => value === null ? null : parse(value)
const integer = (value: unknown, min = 0, max = Number.MAX_SAFE_INTEGER): number => typeof value === 'number' && Number.isSafeInteger(value) && value >= min && value <= max ? value : fail()
const bool = (value: unknown): boolean => typeof value === 'boolean' ? value : fail()
const member = <T extends string>(value: unknown, choices: readonly T[]): T => typeof value === 'string' && choices.includes(value as T) ? value as T : fail()
const array = <T,>(value: unknown, parse: (item: unknown) => T, max = 100): T[] => Array.isArray(value) && value.length <= max ? value.map(parse) : fail()
const date = (value: unknown): string => typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value) && Number.isFinite(Date.parse(value)) && new Date(value).toISOString().slice(0, 10) === value ? value : fail()
const instant = (value: unknown): string => typeof value === 'string' && value.length <= 32 && /^\d{4}-\d{2}-\d{2}T.*(?:Z|[+-]\d{2}:\d{2})$/.test(value) && Number.isFinite(Date.parse(value)) ? value : fail()
const currency = (value: unknown) => member(value, ['INR', 'USD'] as const)
const coverage = (value: unknown) => member(value, ['snapshot', 'partial_activity', 'complete_activity', 'unknown'] as const)
export type Page<T> = { items: T[]; next_after: string | null }
export function page<T extends { id: string }>(value: unknown, parse: (value: unknown) => T, after: string | null = null, size = 25): Page<T> {
  const raw = object(value), items = array(raw.items, parse, size), next = nullable(raw.next_after, id)
  let previous = after
  for (const item of items) { if (previous !== null && item.id <= previous) fail(); previous = item.id }
  if (next !== null && (items.length !== size || next !== previous)) fail()
  return { items, next_after: next }
}
export type Component = { role: string; source: string | null; currency: 'INR' | 'USD' | null; missing_reason: string | null }
const roles = ['quantity', 'unit_price', 'acquisition_cost', 'net_cash', 'gross_cash', 'fee', 'withholding', 'discount_amount', 'reported_tax_basis'] as const
export function component(value: unknown): Component {
  const raw = object(value), source = nullable(raw.source, value => typeof value === 'string' && value.length <= 32 && /^-?(?:0|[1-9]\d{0,17})(?:\.\d{1,12})?$/.test(value) ? value : fail())
  const missing = nullable(raw.missing_reason, value => member(value, ['not_supplied', 'unsupported', 'incomplete_history', 'conflicting_evidence'] as const))
  if ((source === null) !== (missing !== null)) fail()
  const role = member(raw.role, roles), native = nullable(raw.currency, currency)
  if ((role === 'quantity') !== (native === null)) fail()
  const scale = ['net_cash', 'gross_cash'].includes(role) ? 2 : ['quantity', 'unit_price'].includes(role) ? 12 : 8
  if (source && (source.split('.')[1]?.length ?? 0) > scale) fail()
  return { role, source, currency: native, missing_reason: missing }
}
const components = (value: unknown): Component[] => { const items = array(value, component, 8); if (new Set(items.map(item => item.role)).size !== items.length) fail(); return items }
export type Instrument = { id: string; name: string; isin: string; asset_class: string; fund_plan: string | null; fund_option: string | null }
export function instrument(value: unknown): Instrument {
  const raw = object(value), asset = member(raw.asset_class, ['equity', 'etf', 'mutual_fund'] as const)
  const plan = nullable(raw.fund_plan, value => member(value, ['direct', 'regular'] as const)), option = nullable(raw.fund_option, value => member(value, ['growth', 'idcw_payout', 'idcw_reinvestment'] as const))
  if (asset === 'mutual_fund' ? !plan || !option || raw.fund_currency !== 'INR' || !id(raw.fund_scheme_id) : plan !== null || option !== null || raw.fund_scheme_id !== null || raw.fund_currency !== null) fail()
  return { id: id(raw.id), name: text(raw.name), isin: /^[A-Z]{2}[A-Z0-9]{9}\d$/.test(text(raw.isin, 12)) ? String(raw.isin) : fail(), asset_class: asset, fund_plan: plan, fund_option: option }
}
export type Position = { id: string; account_id: string; instrument_id: string; holding_form: string; account_state: string }
export function position(value: unknown): Position { const raw = object(value); return { id: id(raw.id), account_id: id(raw.account_id), instrument_id: id(raw.instrument_id), holding_form: member(raw.holding_form, ['demat', 'folio', 'custody'] as const), account_state: member(raw.account_state, ['active', 'archived'] as const) } }
export type Snapshot = { id: string; revision: number; account_id: string; position_id: string | null; instrument_id: string | null; currency: 'INR' | 'USD' | null; source_id: string; coverage: string; as_of_date: string | null; as_of_instant: string | null; snapshot_scope: string | null; components: Component[]; status: string; is_current: boolean; account_state: string }
export function snapshot(value: unknown): Snapshot {
  const raw = object(value), day = nullable(raw.as_of_date, date), time = nullable(raw.as_of_instant, instant)
  if (time !== null && time.slice(0, 10) !== day) fail()
  return { id: id(raw.id), revision: integer(raw.revision, 1), account_id: id(raw.account_id), position_id: nullable(raw.position_id, id), instrument_id: nullable(raw.instrument_id, id), currency: nullable(raw.currency, currency), source_id: id(raw.source_id), coverage: coverage(raw.coverage), as_of_date: day, as_of_instant: time, snapshot_scope: nullable(raw.snapshot_scope, value => member(value, ['selected_position', 'native_cash', 'full_account'] as const)), components: components(raw.components), status: member(raw.status, ['active', 'cancelled'] as const), is_current: bool(raw.is_current), account_state: member(raw.account_state, ['active', 'archived'] as const) }
}
export type Choice = { id: string; revision: number; position_id: string | null; currency: 'INR' | 'USD' | null; state: string; snapshot: Snapshot | null }
export function choice(value: unknown): Choice {
  const raw = object(value), selected = object(raw.selection), evidence = nullable(raw.snapshot, snapshot), state = member(raw.state, ['selected', 'unselected', 'stale', 'cancelled', 'archived', 'conflicting'] as const)
  if (selected.is_current !== true || (state === 'selected') !== (evidence !== null)) fail()
  if (evidence && (evidence.id !== selected.snapshot_id || evidence.revision !== selected.snapshot_revision || evidence.account_id !== selected.account_id || evidence.position_id !== selected.position_id || evidence.currency !== selected.currency || !evidence.is_current || evidence.status !== 'active' || evidence.account_state !== 'active')) fail()
  return { id: id(selected.id), revision: integer(selected.revision, 1), position_id: nullable(selected.position_id, id), currency: nullable(selected.currency, currency), state, snapshot: evidence }
}
export type Investment = Position & { instrument: Instrument; choices: Choice[] }
export function investment(value: unknown): Investment {
  const raw = object(value), identity = position(raw), security = instrument(raw.instrument), choices = array(raw.choices, choice, 3)
  if (identity.instrument_id !== security.id || choices.some(item => item.position_id !== identity.id || (item.snapshot && (item.snapshot.account_id !== identity.account_id || item.snapshot.instrument_id !== identity.instrument_id)))) fail()
  return { ...identity, instrument: security, choices }
}
export type Batch = { id: string; revision: number; source_id: string; is_current: boolean; source_current: boolean; normalizer: string; row_count: number }
export function batch(value: unknown): Batch { const raw = object(value); return { id: id(raw.id), revision: integer(raw.revision, 1), source_id: id(raw.source_id), is_current: bool(raw.is_current), source_current: bool(raw.source_current), normalizer: text(raw.normalizer, 48), row_count: integer(raw.row_count, 1, 100) } }
export type Row = { id: string; occurrence: number; kind: string; instrument_identifier_id: string | null; as_of_date: string | null; as_of_instant: string | null; components: Component[]; status: string; issue: string | null; review_revision: number }
export type Mapping = { row_id: string; instrument_id: string | null; listing_id: string | null; revision: number }
export type Receipt = { id: string; batch_id: string; created_at: string; row_count: number; selection_count: number }
export function receipt(value: unknown): Receipt { const raw = object(value); if (raw.mode !== 'limited' || raw.coverage !== 'snapshot' || raw.scope_count !== 0) fail(); return { id: id(raw.id), batch_id: id(raw.batch_id), created_at: instant(raw.created_at), row_count: integer(raw.row_count, 1, 100), selection_count: integer(raw.selection_count, 0, 100) } }
export type Inspection = { batch: Batch; account_id: string | null; account_mapping_revision: number; rows: Row[]; mappings: Mapping[]; receipt: Receipt | null }
export function inspection(value: unknown): Inspection {
  const raw = object(value), meta = batch(raw.batch)
  const rows = array(raw.rows, value => {
    const row = object(value), decision = row.decision === null ? null : object(row.decision)
    if (row.batch_id !== meta.id || decision && (decision.id !== row.id || decision.is_current !== true)) fail()
    return { id: id(row.id), occurrence: integer(row.occurrence, 1, 1000000), kind: text(row.kind, 32), instrument_identifier_id: nullable(row.instrument_identifier_id, id), as_of_date: nullable(row.as_of_date, date), as_of_instant: nullable(row.as_of_instant, instant), components: components(row.components), status: member(row.status, ['included', 'excluded', 'reviewable', 'blocked', 'superseded'] as const), issue: nullable(row.issue, value => text(value, 32)), review_revision: decision ? integer(decision.revision, 1) : 0 }
  })
  const mappings = array(raw.mappings, value => { const map = object(value); return { row_id: id(map.row_id), instrument_id: nullable(map.instrument_id, id), listing_id: nullable(map.listing_id, id), revision: integer(map.revision) } })
  if (rows.length !== meta.row_count || new Set(rows.map(item => item.id)).size !== rows.length || mappings.length !== rows.length || mappings.some((item, index) => item.row_id !== rows[index]?.id) || rows.some((item, index) => index > 0 && item.occurrence <= rows[index - 1]!.occurrence)) fail()
  const saved = nullable(raw.receipt, receipt); if (saved && saved.batch_id !== meta.id) fail()
  return { batch: meta, account_id: nullable(raw.account_id, id), account_mapping_revision: integer(raw.account_mapping_revision), rows, mappings, receipt: saved }
}
export type Preview = { token: string; batch_id: string; row_count: number; selection_count: number; expiresAt: number }
export function preview(value: unknown): Preview { const raw = object(value); if (raw.expires_in !== 300 || raw.coverage !== 'snapshot') fail(); return { token: text(raw.token, 100000), batch_id: id(raw.batch_id), row_count: integer(raw.row_count, 1, 100), selection_count: integer(raw.selection_count, 0, 100), expiresAt: performance.now() + 300000 } }
export function exactValue(value: Component, masked: boolean): string {
  if (masked) return '••••'
  if (value.source === null) return `Unavailable · ${value.missing_reason?.replaceAll('_', ' ')}`
  const [whole, fraction] = value.source.split('.')
  return `${value.currency ? `${value.currency} ` : ''}${whole!.replace(/\B(?=(\d{3})+(?!\d))/g, ',')}${fraction === undefined ? '' : `.${fraction}`}`
}
export type SourceObservation = { id: string; source_id: string; previous_id: string | null; is_current: boolean; coverage: 'snapshot' | 'partial_activity' | 'complete_activity' | 'unknown'; period_start: string | null; period_end: string | null }
export function sourceObservation(value: unknown): SourceObservation {
  const raw = object(value), start = nullable(raw.period_start, date), end = nullable(raw.period_end, date), claim = coverage(raw.coverage), identity = id(raw.id), previous = nullable(raw.previous_id, id)
  if ((start === null) !== (end === null) || claim !== 'unknown' && start === null || start !== null && end !== null && start > end || previous === identity) fail()
  return { id: identity, source_id: id(raw.source_id), previous_id: previous, is_current: bool(raw.is_current), coverage: claim, period_start: start, period_end: end }
}
export const coverageLabels = { snapshot: 'Holdings snapshot only', partial_activity: 'Partial activity reported', complete_activity: 'Source claims complete activity', unknown: 'Coverage unknown' } as const
export type FinancePath = '/credit/evidence/query' | '/credit/evidence/history' | '/credit/evidence/inspect' | '/credit/accounts/query' | '/credit/accounts/inspect' | '/credit/sources/query' | '/credit/sources/mappings/history' | '/accounts/query' | '/investments/query' | '/snapshot-review/query' | '/snapshot-review/inspect' | '/snapshot-review/decide' | '/snapshot-review/account-mapping' | '/snapshot-review/instrument-mapping' | '/snapshot-review/position' | '/snapshot-review/preview' | '/snapshot-review/complete' | '/instruments/query' | '/positions/query' | '/snapshots/query' | '/snapshots/selections/query' | '/listings/query' | '/imports/observations/query' | '/lots/query' | '/lots/observations/query' | '/lots/observations/history' | '/events/query' | '/events/history' | '/receipts/query' | '/receipts/rows/query' | '/receipts/scopes/query' | '/receipts/scopes/inspect' | '/receipts/inputs/query'
