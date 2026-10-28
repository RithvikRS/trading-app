import { parseAccountPage } from './accounts'
import type { Account, AccountPage } from './accounts'
import { bankSetupInput } from './bank-setup'

export type BankMappingPath = '/sources/query' | '/bank-source-mappings/history' | '/bank-source-mappings/change'
export const BANK_MAPPING_PAGE_SIZE = 25
export const MAX_BANK_MAPPING_PAGES = 100
export const MAX_BANK_MAPPING_REVISION = Number.MAX_SAFE_INTEGER
const namespaces = ['hdfc_statement', 'sbi_statement', 'indmoney_india', 'indmoney_us', 'indmoney_funds', 'cas', 'advisor', 'ubs_espp'] as const
export type BankSourceNamespace = 'hdfc_statement' | 'sbi_statement'
export type MappingSource = Readonly<{ id: string; namespace: typeof namespaces[number]; mapping_revision: number | null; account_id: string | null; state: 'mapped' | 'unmapped' | 'archived' }>
export type BankMappingScope = Readonly<{ source_id: string; namespace: BankSourceNamespace }>
export type BankMappingTransition = BankMappingScope & Readonly<{ revision: number; previous_revision: number | null; account_id: string | null; reason: 'initial' | 'correction' | 'unlinked' }>
export type BankMappingAnchor = BankMappingScope & Readonly<{ head_revision: number; head: BankMappingTransition | null }>
export type BankMappingHistory = BankMappingAnchor & Readonly<{ items: readonly BankMappingTransition[]; next_before: number | null }>
export type MappingSourcePage = Readonly<{ items: readonly MappingSource[]; next_after: string | null }>
export type MappingCursor = Readonly<{ after: string | null; previous: readonly (string | null)[] }>
export type BankMappingTarget = Readonly<Omit<Account, 'kind' | 'institution' | 'market' | 'state' | 'currencies'> & { kind: 'bank'; institution: 'hdfc' | 'sbi'; market: 'IN'; state: 'active'; currencies: readonly ('INR' | 'USD')[] }>
export type BankMappingCommand = Readonly<{ source_id: string; expected_revision: number; account_id: string | null }>
export type PendingBankMapping = Readonly<{ command: BankMappingCommand; predecessor: BankMappingAnchor; target: BankMappingTarget | null }>
function invalid(): never { throw new Error('Bank source assignments could not be verified.') }
function object(value: unknown, fields: readonly string[]): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) invalid()
  const result = value as Record<string, unknown>
  if (Object.keys(result).length !== fields.length || Object.keys(result).some(key => !fields.includes(key))) invalid()
  return result
}
function identifier(value: unknown): string {
  if (typeof value !== 'string' || value.length !== 36 || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(value) || value === '00000000-0000-0000-0000-000000000000') invalid()
  return value
}
function revision(value: unknown, minimum = 1, maximum = MAX_BANK_MAPPING_REVISION): number { if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < minimum || value > maximum) invalid(); return value }
function member<T extends string>(value: unknown, choices: readonly T[]): T { if (typeof value !== 'string' || !choices.includes(value as T)) invalid(); return value as T }
function nullable<T>(value: unknown, parse: (value: unknown) => T): T | null { return value === null ? null : parse(value) }
export function bankMappingScope(value: unknown): BankMappingScope {
  const raw = object(value, ['source_id', 'namespace'])
  return Object.freeze({ source_id: identifier(raw.source_id), namespace: member(raw.namespace, ['hdfc_statement', 'sbi_statement']) })
}
export function mappingSource(value: unknown): MappingSource {
  const raw = object(value, ['id', 'namespace', 'mapping_revision', 'account_id', 'state'])
  const result = { id: identifier(raw.id), namespace: member(raw.namespace, namespaces), mapping_revision: nullable(raw.mapping_revision, revision), account_id: nullable(raw.account_id, identifier), state: member(raw.state, ['mapped', 'unmapped', 'archived'] as const) }
  if ((result.account_id === null) !== (result.state === 'unmapped') || result.account_id !== null && result.mapping_revision === null) invalid()
  return Object.freeze(result)
}
export function bankMappingTransition(value: unknown): BankMappingTransition {
  const raw = object(value, ['source_id', 'namespace', 'revision', 'previous_revision', 'account_id', 'reason'])
  const scope = bankMappingScope({ source_id: raw.source_id, namespace: raw.namespace })
  const result = { ...scope, revision: revision(raw.revision), previous_revision: nullable(raw.previous_revision, revision), account_id: nullable(raw.account_id, identifier), reason: member(raw.reason, ['initial', 'correction', 'unlinked'] as const) }
  const expectedReason = result.account_id === null ? 'unlinked' : result.revision === 1 ? 'initial' : 'correction'
  if (result.previous_revision !== (result.revision === 1 ? null : result.revision - 1) || result.reason !== expectedReason || result.revision === 1 && result.account_id === null) invalid()
  return Object.freeze(result)
}
export function sameBankMapping(left: BankMappingTransition | null, right: BankMappingTransition | null): boolean {
  return left === null || right === null ? left === right : left.source_id === right.source_id && left.namespace === right.namespace && left.revision === right.revision && left.previous_revision === right.previous_revision && left.account_id === right.account_id && left.reason === right.reason
}
export function bankMappingAnchor(value: unknown): BankMappingAnchor {
  const raw = object(value, ['source_id', 'namespace', 'head_revision', 'head']), scope = bankMappingScope({ source_id: raw.source_id, namespace: raw.namespace })
  const headRevision = revision(raw.head_revision, 0), head = nullable(raw.head, bankMappingTransition)
  if (headRevision === 0 ? head !== null : head === null || head.revision !== headRevision || head.source_id !== scope.source_id || head.namespace !== scope.namespace) invalid()
  return Object.freeze({ ...scope, head_revision: headRevision, head })
}
function retainedHead(next: BankMappingAnchor, previous: BankMappingAnchor) {
  if (next.source_id !== previous.source_id || next.namespace !== previous.namespace || next.head_revision < previous.head_revision || next.head_revision === previous.head_revision && !sameBankMapping(next.head, previous.head)) invalid()
  if (next.head?.previous_revision === previous.head_revision && previous.head !== null && next.head.account_id === previous.head.account_id) invalid()
}
export function bankSourceAnchor(value: MappingSource, previous?: BankMappingAnchor): BankMappingAnchor {
  const source = mappingSource(value), scope = bankMappingScope({ source_id: source.id, namespace: source.namespace }), count = source.mapping_revision ?? 0
  const next = bankMappingAnchor({ ...scope, head_revision: count, head: count === 0 ? null : { ...scope, revision: count, previous_revision: count === 1 ? null : count - 1, account_id: source.account_id, reason: source.account_id === null ? 'unlinked' : count === 1 ? 'initial' : 'correction' } })
  if (previous) retainedHead(next, bankMappingAnchor(previous))
  return next
}
export function mappingSources(value: unknown, after: string | null = null, known: ReadonlyMap<string, BankMappingAnchor> = new Map(), retained: ReadonlyMap<string, BankMappingTransition> = new Map()): MappingSourcePage {
  if (after !== null) identifier(after)
  const raw = object(value, ['items', 'next_after'])
  if (!Array.isArray(raw.items) || raw.items.length > BANK_MAPPING_PAGE_SIZE) invalid()
  const items = raw.items.map(mappingSource), next = nullable(raw.next_after, identifier)
  let previous = after
  for (const item of items) {
    if (previous !== null && item.id <= previous) invalid()
    previous = item.id
    const prior = known.get(item.id)
    if (prior || item.namespace === 'hdfc_statement' || item.namespace === 'sbi_statement') {
      const projected = bankSourceAnchor(item, prior), historical = retained.get(item.id)
      if (historical) retainedHead(projected, bankMappingAnchor({ source_id: historical.source_id, namespace: historical.namespace, head_revision: historical.revision, head: historical }))
    }
  }
  if (next !== null && (items.length !== BANK_MAPPING_PAGE_SIZE || next !== previous)) invalid()
  return Object.freeze({ items: Object.freeze(items), next_after: next })
}
export function mappingAccounts(value: unknown, after: string | null = null, selected?: BankMappingAnchor): AccountPage {
  // Read the entire mixed page before narrowing to eligible bank targets.
  const result = parseAccountPage(value, after)
  if (after !== null) identifier(after)
  for (const account of result.items) identifier(account.id)
  if (result.next_after !== null) identifier(result.next_after)
  if (selected) {
    const anchor = bankMappingAnchor(selected), current = result.items.find(account => account.id === anchor.head?.account_id)
    // A present current target must match the source family; archived and off-page targets remain valid.
    if (current && (current.kind !== 'bank' || current.market !== 'IN' || current.institution !== (anchor.namespace === 'hdfc_statement' ? 'hdfc' : 'sbi'))) invalid()
  }
  return result
}
export function eligibleBankTarget(value: Account, selected: BankMappingScope): BankMappingTarget | null {
  const scope = bankMappingScope(selected)
  if (value.kind !== 'bank' || value.state !== 'active' || value.market !== 'IN' || value.institution !== (scope.namespace === 'hdfc_statement' ? 'hdfc' : 'sbi')) return null
  let input
  try { input = bankSetupInput({ institution: value.institution, label: value.label, currencies: value.currencies }) } catch { return null }
  return Object.freeze({ ...value, kind: 'bank', institution: input.institution, market: 'IN', state: 'active', label: input.label, currencies: input.currencies })
}
export function bankMappingHistory(value: unknown, selected: BankMappingAnchor, before: number | null = null, minimumRevision = selected.head_revision, retained?: BankMappingTransition): BankMappingHistory {
  const previous = bankMappingAnchor(selected), raw = object(value, ['source_id', 'namespace', 'head_revision', 'head', 'items', 'next_before'])
  if (before !== null) revision(before)
  const next = bankMappingAnchor({ source_id: raw.source_id, namespace: raw.namespace, head_revision: raw.head_revision, head: raw.head })
  retainedHead(next, previous)
  if (revision(minimumRevision, 0) < previous.head_revision || next.head_revision < minimumRevision) invalid()
  const historical = retained === undefined ? null : bankMappingTransition(retained)
  if (historical && (historical.source_id !== next.source_id || historical.namespace !== next.namespace || historical.revision > next.head_revision)) invalid()
  if (!Array.isArray(raw.items) || raw.items.length > BANK_MAPPING_PAGE_SIZE) invalid()
  const items = raw.items.map(bankMappingTransition), cursor = nullable(raw.next_before, revision)
  const start = before === null ? next.head_revision : Math.min(next.head_revision, before - 1)
  if (items.length !== Math.min(start, BANK_MAPPING_PAGE_SIZE)) invalid()
  for (const [index, item] of items.entries()) if (item.source_id !== next.source_id || item.namespace !== next.namespace || item.revision !== start - index) invalid()
  const last = items.at(-1)
  if (cursor !== (last && last.revision > 1 ? last.revision : null)) invalid()
  // Equal revision tuples must stay identical, including an earlier retained head in this page.
  const revisions = new Map<number, BankMappingTransition>()
  for (const item of [previous.head, next.head, historical, ...items]) {
    if (item === null) continue
    const retained = revisions.get(item.revision)
    if (retained && !sameBankMapping(retained, item)) invalid()
    revisions.set(item.revision, item)
  }
  for (const item of revisions.values()) {
    const predecessor = item.previous_revision === null ? undefined : revisions.get(item.previous_revision)
    if (predecessor && predecessor.account_id === item.account_id) invalid()
  }
  return Object.freeze({ ...next, items: Object.freeze(items), next_before: cursor })
}
export function bankMappingChange(selected: BankMappingAnchor, target: BankMappingTarget | null): PendingBankMapping {
  const predecessor = bankMappingAnchor(selected)
  revision(predecessor.head_revision, 0, MAX_BANK_MAPPING_REVISION - 1)
  let checkedTarget: BankMappingTarget | null = null
  if (target !== null) {
    const page = mappingAccounts({ items: [{ ...target, currencies: [...target.currencies] }], next_after: null })
    checkedTarget = eligibleBankTarget(page.items[0]!, { source_id: predecessor.source_id, namespace: predecessor.namespace })
    if (!checkedTarget) invalid()
  }
  const account_id = checkedTarget?.id ?? null
  if (account_id === (predecessor.head?.account_id ?? null)) invalid()
  const command = Object.freeze({ source_id: predecessor.source_id, expected_revision: predecessor.head_revision, account_id })
  return Object.freeze({ command, predecessor, target: checkedTarget })
}
export function bankMappingResult(value: unknown, pending: PendingBankMapping): BankMappingTransition {
  const checked = bankMappingChange(pending.predecessor, pending.target)
  if (pending.command.source_id !== checked.command.source_id || pending.command.expected_revision !== checked.command.expected_revision || pending.command.account_id !== checked.command.account_id) invalid()
  const result = bankMappingTransition(value), command = checked.command
  if (result.source_id !== command.source_id || result.namespace !== checked.predecessor.namespace || result.revision !== command.expected_revision + 1 || result.previous_revision !== (command.expected_revision || null) || result.account_id !== command.account_id) invalid()
  return result
}
export const bankSourceState = (source: MappingSource) => source.mapping_revision === null ? 'Never linked' : source.state === 'unmapped' ? 'Explicitly unlinked' : source.state === 'archived' ? 'Linked to archived account' : 'Linked'
