export const CREDIT_PAGE_SIZE = 25
export const CREDIT_MAX_PAGES = 100
export type CreditAccount = { id: string; issuer: 'hdfc'; billing_currency: 'INR'; label: string; revision: number; state: 'active' | 'archived' }
export type CreditSource = { id: string; family: 'hdfc_credit_statement'; mapping_revision: number | null; account_id: string | null; state: 'mapped' | 'unmapped' | 'archived' }
export type CreditMapping = { source_id: string; revision: number; previous_revision: number | null; account_id: string | null; reason: 'initial' | 'correction' | 'unlinked'; is_latest_revision: boolean; account_state: 'active' | 'archived' | null }
export type CreditPage<T> = { items: T[]; next_after: string | null }
export type CreditHistory = { items: CreditMapping[]; next_before: number | null }
export type CreditCursor = { after: string | null; previous: (string | null)[] }
function invalid(): never { throw new Error('Saved credit identity could not be verified.') }
function object(value: unknown, fields: readonly string[]): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) invalid()
  const result = value as Record<string, unknown>
  if (Object.keys(result).length !== fields.length || Object.keys(result).some(key => !fields.includes(key))) invalid()
  return result
}
function id(value: unknown): string {
  if (typeof value !== 'string' || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(value) || value === '00000000-0000-0000-0000-000000000000') invalid()
  return value
}
function revision(value: unknown): number { if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < 1) invalid(); return value }
function member<T extends string>(value: unknown, choices: readonly T[]): T { if (typeof value !== 'string' || !choices.includes(value as T)) invalid(); return value as T }
function nullable<T>(value: unknown, parse: (value: unknown) => T): T | null { return value === null ? null : parse(value) }
export function creditAccount(value: unknown): CreditAccount {
  const raw = object(value, ['id', 'issuer', 'billing_currency', 'label', 'revision', 'state'])
  if (typeof raw.label !== 'string' || !/^[A-Za-z][A-Za-z .()-]{0,63}$/.test(raw.label)) invalid()
  return { id: id(raw.id), issuer: member(raw.issuer, ['hdfc']), billing_currency: member(raw.billing_currency, ['INR']), label: raw.label, revision: revision(raw.revision), state: member(raw.state, ['active', 'archived']) }
}
export function creditAccountInspection(value: unknown, selected: string | CreditAccount): CreditAccount {
  const result = creditAccount(value), expected = typeof selected === 'string' ? id(selected) : creditAccount(selected).id
  if (result.id !== expected) invalid()
  if (typeof selected !== 'string' && (result.revision < selected.revision || result.revision === selected.revision && (result.label !== selected.label || result.state !== selected.state))) invalid()
  return result
}
export function creditSource(value: unknown): CreditSource {
  const raw = object(value, ['id', 'family', 'mapping_revision', 'account_id', 'state'])
  const result: CreditSource = { id: id(raw.id), family: member(raw.family, ['hdfc_credit_statement']), mapping_revision: nullable(raw.mapping_revision, revision), account_id: nullable(raw.account_id, id), state: member(raw.state, ['mapped', 'unmapped', 'archived']) }
  if ((result.account_id === null) !== (result.state === 'unmapped') || result.account_id !== null && result.mapping_revision === null) invalid()
  return result
}
function page<T extends { id: string }>(value: unknown, after: string | null, parse: (value: unknown) => T): CreditPage<T> {
  if (after !== null) id(after)
  const raw = object(value, ['items', 'next_after'])
  if (!Array.isArray(raw.items) || raw.items.length > CREDIT_PAGE_SIZE) invalid()
  const items = raw.items.map(parse), next = nullable(raw.next_after, id)
  let previous = after
  for (const item of items) { if (previous !== null && item.id <= previous) invalid(); previous = item.id }
  if (next !== null && (items.length !== CREDIT_PAGE_SIZE || next !== previous)) invalid()
  return { items, next_after: next }
}
export const creditAccounts = (value: unknown, after: string | null = null): CreditPage<CreditAccount> => page(value, after, creditAccount)
export const creditSources = (value: unknown, after: string | null = null): CreditPage<CreditSource> => page(value, after, creditSource)
function mapping(value: unknown): CreditMapping {
  const raw = object(value, ['source_id', 'revision', 'previous_revision', 'account_id', 'reason', 'is_latest_revision', 'account_state'])
  if (typeof raw.is_latest_revision !== 'boolean') invalid()
  const result: CreditMapping = { source_id: id(raw.source_id), revision: revision(raw.revision), previous_revision: nullable(raw.previous_revision, revision), account_id: nullable(raw.account_id, id), reason: member(raw.reason, ['initial', 'correction', 'unlinked']), is_latest_revision: raw.is_latest_revision, account_state: nullable(raw.account_state, value => member(value, ['active', 'archived'])) }
  if (result.previous_revision !== (result.revision === 1 ? null : result.revision - 1) || (result.reason === 'initial') !== (result.revision === 1) || (result.reason === 'unlinked') !== (result.account_id === null) || (result.account_id === null) !== (result.account_state === null)) invalid()
  return result
}
export function creditMappingHistory(value: unknown, selected: CreditSource, before: number | null = null, minimumRevision = selected.mapping_revision): CreditHistory {
  const source = creditSource(selected), raw = object(value, ['items', 'next_before'])
  if (before !== null) revision(before)
  if (minimumRevision === null ? source.mapping_revision !== null : revision(minimumRevision) < (source.mapping_revision ?? 0)) invalid()
  if (!Array.isArray(raw.items) || raw.items.length > CREDIT_PAGE_SIZE) invalid()
  const items = raw.items.map(mapping), next = nullable(raw.next_before, revision)
  if (!items.length) {
    if (next !== null || before === null && minimumRevision !== null || before !== null && before !== 1) invalid()
    return { items, next_before: null }
  }
  const first = items[0]!
  if (before === null ? !first.is_latest_revision || minimumRevision !== null && first.revision < minimumRevision : first.revision !== before - 1 || first.is_latest_revision) invalid()
  for (let index = 0; index < items.length; index++) {
    const item = items[index]!
    if (item.source_id !== source.id || index > 0 && (item.revision !== items[index - 1]!.revision - 1 || item.is_latest_revision)) invalid()
    if (item.revision === source.mapping_revision && item.account_id !== source.account_id) invalid()
  }
  const last = items.at(-1)!
  if (last.revision === 1 ? next !== null : items.length !== CREDIT_PAGE_SIZE || next !== last.revision) invalid()
  return { items, next_before: next }
}
export function creditSourceState(source: CreditSource): string { return source.mapping_revision === null ? 'Never linked' : source.state === 'unmapped' ? 'Unlinked' : source.state === 'archived' ? 'Linked to archived account' : 'Linked' }
