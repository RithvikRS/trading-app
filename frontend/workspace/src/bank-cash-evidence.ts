import { bankAccount } from './banking-evidence'
import type { BankAccount } from './banking-evidence'
import { id as sharedId, component } from './investments'
import type { Component, Page } from './investments'

export type NativeCurrency = 'INR' | 'USD'
export const CASH_PAGE_SIZE = 25
export const MAX_CASH_PAGES = 100
export const MAX_CASH_ROOTS = 100
export type CashScope = { account: BankAccount; currency: NativeCurrency }
export type CashSelection = { id: string; revision: number; is_current: boolean; account_id: string; position_id: null; currency: NativeCurrency; snapshot_id: string | null; snapshot_revision: number | null; reason: 'reviewed' | 'newer_evidence' | 'correction' | 'clear' }
export type CashSnapshot = {
  id: string; revision: number; is_current: boolean; account_id: string; account_state: 'active' | 'archived'
  position_id: null; instrument_id: null; currency: NativeCurrency; kind: 'cash_snapshot'
  status: 'active' | 'cancelled'; correction_reason: 'source_correction' | 'cancellation' | 'reinstatement' | null
  as_of_date: string | null; as_of_instant: string | null; snapshot_scope: 'native_cash' | 'full_account' | null
  reconciliation_boundary: 'before_period' | 'after_period' | null; booking_date: string | null
  source_row_id: string; source_review_revision: number; source_id: string; observation_id: string; batch_id: string
  coverage: 'snapshot' | 'partial_activity' | 'complete_activity' | 'unknown'; period_start: string | null; period_end: string | null
  cash_date_basis: 'booking' | 'value' | 'settlement' | null; components: Component[]
}
export type CashResolution = { selection: CashSelection; state: 'selected' | 'unselected' | 'stale' | 'cancelled' | 'archived' | 'conflicting'; snapshot: CashSnapshot | null }
export type CashHistory<T> = { items: T[]; next_before: number | null }
export type HistoryRead = { mode: 'latest'; before: null } | { mode: 'earlier'; before: number } | { mode: 'pin'; before: number | null; revision: number }
export const latestCashHistory: HistoryRead = { mode: 'latest', before: null }
export function pinnedCashHistory(value: number): HistoryRead { const version = revision(value); return { mode: 'pin', revision: version, before: version === Number.MAX_SAFE_INTEGER ? null : version + 1 } }
function invalid(): never { throw new Error('Saved bank cash could not be verified.') }
function object(value: unknown, fields: readonly string[]): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) invalid()
  const raw = value as Record<string, unknown>, keys = Object.keys(raw)
  if (keys.length !== fields.length || keys.some(key => !fields.includes(key))) invalid()
  return raw
}
const id = (value: unknown): string => typeof value === 'string' && value.length === 36 ? sharedId(value) : invalid()
const nullable = <T,>(value: unknown, parse: (value: unknown) => T): T | null => value === null ? null : parse(value)
const member = <T extends string>(value: unknown, choices: readonly T[]): T => typeof value === 'string' && choices.includes(value as T) ? value as T : invalid()
const revision = (value: unknown): number => typeof value === 'number' && Number.isSafeInteger(value) && value > 0 ? value : invalid()
const boolean = (value: unknown): boolean => typeof value === 'boolean' ? value : invalid()
function day(value: unknown): string {
  if (typeof value !== 'string' || !/^(?!0000)[0-9]{4}-[0-9]{2}-[0-9]{2}$/.test(value) || !Number.isFinite(Date.parse(value)) || new Date(value).toISOString().slice(0, 10) !== value) invalid()
  return value
}
function instant(value: unknown, date: string | null): string {
  if (typeof value !== 'string' || value.length > 32 || /[\u0000-\u0020\u007f]/.test(value) || !/^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})$/.test(value) || day(value.slice(0, 10)) !== date) invalid()
  const offset = value.endsWith('Z') ? 'Z' : value.slice(-6)
  if (Number(value.slice(11, 13)) > 23 || Number(value.slice(14, 16)) > 59 || Number(value.slice(17, 19)) > 59 || offset !== 'Z' && (offset === '-00:00' || Number(offset.slice(1, 3)) > 14 || Number(offset.slice(4)) > 59 || Number(offset.slice(1, 3)) === 14 && Number(offset.slice(4)) !== 0)) invalid()
  const parsed = new Date(value)
  if (!Number.isFinite(parsed.valueOf()) || parsed.getUTCFullYear() < 1 || parsed.getUTCFullYear() > 9999) invalid()
  return value
}
function native(value: unknown, account: BankAccount): NativeCurrency {
  const currency = member(value, ['INR', 'USD'] as const)
  if (!account.currencies.includes(currency)) invalid()
  return currency
}
export function cashScope(account: BankAccount, currency: unknown): CashScope {
  const valid = bankAccount(account)
  return { account: valid, currency: native(currency, valid) }
}
export function cashSelection(value: unknown, account: BankAccount, currency?: NativeCurrency): CashSelection {
  const valid = bankAccount(account), raw = object(value, ['id', 'revision', 'is_current', 'account_id', 'position_id', 'currency', 'snapshot_id', 'snapshot_revision', 'reason'])
  const result: CashSelection = { id: id(raw.id), revision: revision(raw.revision), is_current: boolean(raw.is_current), account_id: id(raw.account_id), position_id: null, currency: native(raw.currency, valid), snapshot_id: nullable(raw.snapshot_id, id), snapshot_revision: nullable(raw.snapshot_revision, revision), reason: member(raw.reason, ['reviewed', 'newer_evidence', 'correction', 'clear'] as const) }
  if (raw.position_id !== null || result.account_id !== valid.id || currency !== undefined && result.currency !== currency || (result.snapshot_id === null) !== (result.snapshot_revision === null) || (result.reason === 'clear') !== (result.snapshot_id === null) || result.revision === 1 && result.reason === 'clear') invalid()
  return result
}
export type ChoiceProgress = { pages: number; ids: string[]; currencies: NativeCurrency[] }
export const emptyCashChoices: ChoiceProgress = { pages: 0, ids: [], currencies: [] }
export function cashChoicePage(value: unknown, account: BankAccount, after: string | null = null, preceding: ChoiceProgress = emptyCashChoices): Page<CashSelection> & { progress: ChoiceProgress } {
  const raw = object(value, ['items', 'next_after'])
  if (after !== null) id(after)
  if (!Number.isSafeInteger(preceding.pages) || preceding.pages < 0 || preceding.pages >= MAX_CASH_PAGES || (after === null) !== (preceding.pages === 0) || preceding.ids.length !== preceding.currencies.length || preceding.ids.length > 2 || new Set(preceding.ids).size !== preceding.ids.length || new Set(preceding.currencies).size !== preceding.currencies.length) invalid()
  for (const identity of preceding.ids) id(identity)
  for (const currency of preceding.currencies) native(currency, bankAccount(account))
  if (after !== null && preceding.ids.at(-1) !== after) invalid()
  if (preceding.pages === 0 && preceding.ids.length || !Array.isArray(raw.items) || raw.items.length > CASH_PAGE_SIZE) invalid()
  const items = raw.items.map(item => cashSelection(item, account)), next = nullable(raw.next_after, id)
  const ids = [...preceding.ids], currencies = [...preceding.currencies]
  let previous = after
  for (const item of items) {
    if (!item.is_current || previous !== null && item.id <= previous || ids.includes(item.id) || currencies.includes(item.currency)) invalid()
    ids.push(item.id); currencies.push(item.currency); previous = item.id
  }
  if (next !== null && (items.length !== CASH_PAGE_SIZE || next !== previous)) invalid()
  return { items, next_after: next, progress: { pages: preceding.pages + 1, ids, currencies } }
}
export function cashSnapshot(value: unknown, scope: CashScope): CashSnapshot {
  const valid = cashScope(scope.account, scope.currency)
  const raw = object(value, ['id', 'revision', 'is_current', 'account_id', 'account_state', 'position_id', 'instrument_id', 'currency', 'kind', 'status', 'correction_reason', 'as_of_date', 'as_of_instant', 'snapshot_scope', 'reconciliation_boundary', 'booking_date', 'source_row_id', 'source_review_revision', 'source_id', 'observation_id', 'batch_id', 'coverage', 'period_start', 'period_end', 'cash_date_basis', 'components'])
  const date = nullable(raw.as_of_date, day)
  const result: CashSnapshot = { id: id(raw.id), revision: revision(raw.revision), is_current: boolean(raw.is_current), account_id: id(raw.account_id), account_state: member(raw.account_state, ['active', 'archived'] as const), position_id: null, instrument_id: null, currency: native(raw.currency, valid.account), kind: 'cash_snapshot', status: member(raw.status, ['active', 'cancelled'] as const), correction_reason: nullable(raw.correction_reason, value => member(value, ['source_correction', 'cancellation', 'reinstatement'] as const)), as_of_date: date, as_of_instant: nullable(raw.as_of_instant, value => instant(value, date)), snapshot_scope: nullable(raw.snapshot_scope, value => member(value, ['native_cash', 'full_account'] as const)), reconciliation_boundary: nullable(raw.reconciliation_boundary, value => member(value, ['before_period', 'after_period'] as const)), booking_date: nullable(raw.booking_date, day), source_row_id: id(raw.source_row_id), source_review_revision: revision(raw.source_review_revision), source_id: id(raw.source_id), observation_id: id(raw.observation_id), batch_id: id(raw.batch_id), coverage: member(raw.coverage, ['snapshot', 'partial_activity', 'complete_activity', 'unknown'] as const), period_start: nullable(raw.period_start, day), period_end: nullable(raw.period_end, day), cash_date_basis: nullable(raw.cash_date_basis, value => member(value, ['booking', 'value', 'settlement'] as const)), components: [] }
  if (raw.kind !== 'cash_snapshot' || raw.position_id !== null || raw.instrument_id !== null || result.account_id !== valid.account.id || result.currency !== valid.currency || (result.revision === 1) !== (result.correction_reason === null) || (result.status === 'cancelled') !== (result.correction_reason === 'cancellation') || (result.period_start === null) !== (result.period_end === null) || result.coverage !== 'unknown' && result.period_start === null || result.period_start !== null && result.period_end !== null && result.period_start > result.period_end || result.reconciliation_boundary !== null && (result.snapshot_scope !== 'native_cash' || result.as_of_date === null) || valid.account.state === 'archived' && result.account_state !== 'archived' || !Array.isArray(raw.components)) invalid()
  if (result.status === 'cancelled') {
    if (raw.components.length !== 0 || result.booking_date === null || result.as_of_instant !== null || result.snapshot_scope !== null || result.reconciliation_boundary !== null) invalid()
  } else {
    if (raw.components.length !== 1 || date === null) invalid()
    const parsed = component(object(raw.components[0], ['role', 'source', 'currency', 'missing_reason']))
    if (parsed.role !== 'net_cash' || parsed.source === null || /[^0-9.\-]/.test(parsed.source) || parsed.missing_reason !== null || parsed.currency !== valid.currency) invalid()
    result.components = [parsed]
  }
  return result
}
function selectionFacts(value: CashSelection): string { const { is_current: _current, ...facts } = value; return JSON.stringify(facts) }
function snapshotFacts(value: CashSnapshot): string { const { is_current: _current, account_state: _state, ...facts } = value; return JSON.stringify(facts) }
export function observeSelection(previous: CashSelection | undefined, value: CashSelection): CashSelection {
  if (!previous) return value
  if (previous.id !== value.id || previous.account_id !== value.account_id || previous.currency !== value.currency || previous.revision === value.revision && selectionFacts(previous) !== selectionFacts(value) || value.is_current && value.revision < previous.revision) invalid()
  return value.revision > previous.revision ? value : previous
}
export function observeSnapshot(previous: CashSnapshot | undefined, value: CashSnapshot): CashSnapshot {
  if (!previous) return value
  if (previous.account_state === 'archived' && value.account_state !== 'archived') invalid()
  if (previous.id !== value.id || previous.account_id !== value.account_id || previous.currency !== value.currency || previous.revision === value.revision && snapshotFacts(previous) !== snapshotFacts(value) || value.is_current && value.revision < previous.revision) invalid()
  return value.revision > previous.revision ? value : previous
}
export function cashResolution(value: unknown, scope: CashScope, opened: CashSelection, head: CashSelection = opened, snapshotHead?: CashSnapshot): CashResolution {
  const raw = object(value, ['selection', 'state', 'snapshot']), selection = cashSelection(raw.selection, scope.account, scope.currency)
  if (!selection.is_current || selection.revision < head.revision) invalid()
  observeSelection(opened, selection); observeSelection(head, selection)
  const state = member(raw.state, ['selected', 'unselected', 'stale', 'cancelled', 'archived', 'conflicting'] as const), snapshot = nullable(raw.snapshot, value => cashSnapshot(value, scope))
  if ((state === 'selected') !== (snapshot !== null) || (state === 'unselected') !== (selection.snapshot_id === null)) invalid()
  if (snapshot && (scope.account.state === 'archived' || snapshot.id !== selection.snapshot_id || snapshot.revision !== selection.snapshot_revision || !snapshot.is_current || snapshot.status !== 'active' || snapshot.account_state !== 'active')) invalid()
  if (snapshot && snapshotHead) observeSnapshot(snapshotHead, snapshot)
  return { selection, state, snapshot }
}
function history<T extends { id: string; revision: number; is_current: boolean }>(value: unknown, parse: (value: unknown) => T, read: HistoryRead, root: T, head: T, compare: (a: T | undefined, b: T) => T): CashHistory<T> {
  const raw = object(value, ['items', 'next_before'])
  if (read.mode !== 'latest' && read.before !== null) revision(read.before)
  if (read.mode === 'latest' && read.before !== null || read.mode === 'pin' && read.before !== pinnedCashHistory(read.revision).before || !['latest', 'earlier', 'pin'].includes(read.mode) || !Array.isArray(raw.items) || raw.items.length > CASH_PAGE_SIZE) invalid()
  const items = raw.items.map(parse), next = nullable(raw.next_before, revision)
  if (!items.length) { if (read.mode !== 'earlier' || read.before !== 1 || next !== null) invalid(); return { items, next_before: null } }
  const first = items[0]!
  if (read.mode === 'latest' ? !first.is_current || first.revision < head.revision : read.mode === 'pin' ? first.revision !== read.revision : first.revision !== read.before - 1 || first.is_current) invalid()
  items.forEach((item, index) => {
    if (item.id !== root.id || index > 0 && (item.revision !== items[index - 1]!.revision - 1 || item.is_current)) invalid()
    compare(root, item); compare(head, item)
  })
  const last = items.at(-1)!
  if (last.revision === 1 ? next !== null : items.length !== CASH_PAGE_SIZE || next !== last.revision) invalid()
  return { items, next_before: next }
}
export function cashSelectionHistory(value: unknown, scope: CashScope, origin: CashSelection, head: CashSelection = origin, read: HistoryRead = latestCashHistory): CashHistory<CashSelection> {
  const root = cashSelection(origin, scope.account, scope.currency), current = cashSelection(head, scope.account, scope.currency)
  observeSelection(root, current)
  return history(value, value => cashSelection(value, scope.account, scope.currency), read, root, current, observeSelection)
}
function retainedSnapshot(value: CashSnapshot, scope: CashScope): CashSnapshot {
  // These anchors were validated when observed. Later archival must not invalidate
  // their original lifecycle metadata; every fresh row still uses the actual scope.
  return cashSnapshot(value, { ...scope, account: { ...scope.account, state: 'active' } })
}
export function cashSnapshotHistory(value: unknown, scope: CashScope, pin: { id: string; revision: number }, head: CashSnapshot | undefined, read: HistoryRead, origin?: CashSnapshot): CashHistory<CashSnapshot> {
  id(pin.id); revision(pin.revision)
  if (origin && (origin.id !== pin.id || origin.revision !== pin.revision) || head && head.id !== pin.id) invalid()
  const raw = object(value, ['items', 'next_before'])
  if (!Array.isArray(raw.items)) invalid()
  if (!raw.items.length) {
    const retained = origin ?? head
    if (!retained || retained.id !== pin.id) invalid()
    return history(value, value => cashSnapshot(value, scope), read, retainedSnapshot(retained, scope), retainedSnapshot(head ?? retained, scope), observeSnapshot)
  }
  // The first verified payload supplies no new scope: account/currency/root were pinned.
  const first = cashSnapshot(raw.items[0], scope)
  if (first.id !== pin.id || origin && (origin.id !== pin.id || origin.revision !== pin.revision) || head && head.id !== pin.id) invalid()
  const root = origin ? retainedSnapshot(origin, scope) : first
  const current = head ? retainedSnapshot(head, scope) : first
  if (read.mode === 'pin' && read.revision !== pin.revision) invalid()
  if (read.mode === 'latest' && first.revision < pin.revision) invalid()
  const result = history(value, value => cashSnapshot(value, scope), read, root, current, observeSnapshot)
  if (result.items.some(item => item.account_state !== first.account_state)) invalid()
  return result
}
