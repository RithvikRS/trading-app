import { CREDIT_PAGE_SIZE, creditAccount } from './credit-identities'
import type { CreditAccount, CreditPage } from './credit-identities'
import { id } from './investments'

export type CreditKind = 'statement' | 'current' | 'entry'
export type CreditCash = { source: string | null; currency: 'INR' | 'USD'; missing_reason: 'not_supplied' | 'incomplete_history' | 'unsupported' | 'conflicting_evidence' | null }
export type CreditStatement = { period_start: string; period_end: string; statement_date: string; due_date: string | null; opening_liability: CreditCash; closing_liability: CreditCash; total_due: CreditCash; minimum_due: CreditCash }
export type CreditCurrent = { as_of_date: string; as_of_instant: string | null; outstanding: CreditCash; unbilled: CreditCash; credit_limit: CreditCash; available_credit: CreditCash }
export type CreditEntry = { role: 'posted_debit' | 'posted_credit' | 'pending_debit' | 'pending_credit' | 'unresolved'; treatment: 'movement' | 'ambiguous' | 'unsupported'; transaction_date: string | null; posting_date: string | null; billing_amount: CreditCash; original_amount: CreditCash | null }
type EvidenceBase = { id: string; revision: number; previous_revision: number | null; source_id: string; mapping_revision: number; account_id: string; account_state: 'active' | 'archived'; is_latest_revision: boolean }
export type CreditEvidence = EvidenceBase & ({ kind: 'statement'; values: CreditStatement } | { kind: 'current'; values: CreditCurrent } | { kind: 'entry'; values: CreditEntry })
export type CreditEvidenceHistory = { items: CreditEvidence[]; next_before: number | null }
function invalid(): never { throw new Error('Saved credit evidence could not be verified.') }
function object(value: unknown, fields: readonly string[]): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) invalid()
  const raw = value as Record<string, unknown>, keys = Object.keys(raw)
  if (keys.length !== fields.length || keys.some(key => !fields.includes(key))) invalid()
  return raw
}
const nullable = <T,>(value: unknown, parse: (value: unknown) => T): T | null => value === null ? null : parse(value)
const choice = <T extends string>(value: unknown, choices: readonly T[]): T => typeof value === 'string' && choices.includes(value as T) ? value as T : invalid()
const revision = (value: unknown): number => typeof value === 'number' && Number.isSafeInteger(value) && value > 0 ? value : invalid()
const boolean = (value: unknown): boolean => typeof value === 'boolean' ? value : invalid()
function day(value: unknown): string {
  if (typeof value !== 'string' || !/^[0-9]{4}-[0-9]{2}-[0-9]{2}$/.test(value) || value.startsWith('0000-') || !Number.isFinite(Date.parse(value)) || new Date(value).toISOString().slice(0, 10) !== value) invalid()
  return value
}
function instant(value: unknown, date: string): string {
  if (typeof value !== 'string' || value.length > 32 || !/^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})$/.test(value) || day(value.slice(0, 10)) !== date) invalid()
  const offset = value.endsWith('Z') ? 'Z' : value.slice(-6)
  if (Number(value.slice(11, 13)) > 23 || Number(value.slice(14, 16)) > 59 || Number(value.slice(17, 19)) > 59 || offset !== 'Z' && (Number(offset.slice(1, 3)) > 14 || Number(offset.slice(4)) > 59 || Number(offset.slice(1, 3)) === 14 && Number(offset.slice(4)) !== 0 || offset === '-00:00')) invalid()
  const parsed = new Date(value)
  if (!Number.isFinite(parsed.valueOf()) || parsed.getUTCFullYear() < 1 || parsed.getUTCFullYear() > 9999) invalid()
  return value
}
function cash(value: unknown, original = false, nonnegative = false): CreditCash {
  const raw = object(value, ['source', 'currency', 'missing_reason']), currency = choice(raw.currency, original ? ['INR', 'USD'] as const : ['INR'] as const)
  const missing = nullable(raw.missing_reason, value => choice(value, ['not_supplied', 'incomplete_history', 'unsupported', 'conflicting_evidence'] as const))
  if (raw.source === null) { if (missing === null) invalid(); return { source: null, currency, missing_reason: missing } }
  if (typeof raw.source !== 'string' || raw.source.length > 32 || !/^-?(?:0|[1-9][0-9]{0,17})(?:\.[0-9]{1,2})?$/.test(raw.source) || missing !== null || nonnegative && raw.source.startsWith('-') && !/^-0(?:\.0{1,2})?$/.test(raw.source)) invalid()
  return { source: raw.source, currency, missing_reason: null }
}
function statement(value: unknown): CreditStatement {
  const raw = object(value, ['period_start', 'period_end', 'statement_date', 'due_date', 'opening_liability', 'closing_liability', 'total_due', 'minimum_due'])
  const result = { period_start: day(raw.period_start), period_end: day(raw.period_end), statement_date: day(raw.statement_date), due_date: nullable(raw.due_date, day), opening_liability: cash(raw.opening_liability), closing_liability: cash(raw.closing_liability), total_due: cash(raw.total_due), minimum_due: cash(raw.minimum_due, false, true) }
  if (result.period_start > result.period_end) invalid()
  return result
}
function current(value: unknown): CreditCurrent {
  const raw = object(value, ['as_of_date', 'as_of_instant', 'outstanding', 'unbilled', 'credit_limit', 'available_credit']), date = day(raw.as_of_date)
  return { as_of_date: date, as_of_instant: nullable(raw.as_of_instant, value => instant(value, date)), outstanding: cash(raw.outstanding), unbilled: cash(raw.unbilled), credit_limit: cash(raw.credit_limit, false, true), available_credit: cash(raw.available_credit) }
}
function entry(value: unknown): CreditEntry {
  const raw = object(value, ['role', 'treatment', 'transaction_date', 'posting_date', 'billing_amount', 'original_amount'])
  const result = { role: choice(raw.role, ['posted_debit', 'posted_credit', 'pending_debit', 'pending_credit', 'unresolved'] as const), treatment: choice(raw.treatment, ['movement', 'ambiguous', 'unsupported'] as const), transaction_date: nullable(raw.transaction_date, day), posting_date: nullable(raw.posting_date, day), billing_amount: cash(raw.billing_amount, false, true), original_amount: nullable(raw.original_amount, value => cash(value, true, true)) }
  if ((result.role === 'pending_debit' || result.role === 'pending_credit') && result.posting_date !== null || result.role === 'unresolved' && result.treatment === 'movement') invalid()
  return result
}
export function creditEvidence(value: unknown, selected: CreditAccount, kind: CreditKind): CreditEvidence {
  const account = creditAccount(selected), raw = object(value, ['id', 'kind', 'revision', 'previous_revision', 'source_id', 'mapping_revision', 'account_id', 'account_state', 'is_latest_revision', 'values'])
  const base = { id: id(raw.id), revision: revision(raw.revision), previous_revision: nullable(raw.previous_revision, revision), source_id: id(raw.source_id), mapping_revision: revision(raw.mapping_revision), account_id: id(raw.account_id), account_state: choice(raw.account_state, ['active', 'archived'] as const), is_latest_revision: boolean(raw.is_latest_revision) }
  if (base.account_id !== account.id || raw.kind !== kind || base.previous_revision !== (base.revision === 1 ? null : base.revision - 1)) invalid()
  if (kind === 'statement') return { ...base, kind, values: statement(raw.values) }
  if (kind === 'current') return { ...base, kind, values: current(raw.values) }
  if (kind !== 'entry') invalid()
  return { ...base, kind, values: entry(raw.values) }
}
function sameRetained(a: CreditEvidence, b: CreditEvidence): boolean {
  return a.id === b.id && a.account_id === b.account_id && a.kind === b.kind && a.source_id === b.source_id && a.revision === b.revision && a.mapping_revision === b.mapping_revision && a.previous_revision === b.previous_revision && JSON.stringify(a.values) === JSON.stringify(b.values)
}
export function creditEvidencePage(value: unknown, account: CreditAccount, kind: CreditKind, after: string | null = null): CreditPage<CreditEvidence> {
  if (after !== null) id(after)
  const raw = object(value, ['items', 'next_after'])
  if (!Array.isArray(raw.items) || raw.items.length > CREDIT_PAGE_SIZE) invalid()
  const items = raw.items.map(value => creditEvidence(value, account, kind)), next = nullable(raw.next_after, id)
  let previous = after
  for (const item of items) { if (!item.is_latest_revision || previous !== null && item.id <= previous || item.account_state !== items[0]!.account_state) invalid(); previous = item.id }
  if (next !== null && (items.length !== CREDIT_PAGE_SIZE || next !== previous)) invalid()
  return { items, next_after: next }
}
export function creditEvidenceHistory(value: unknown, account: CreditAccount, selected: CreditEvidence, before: number | null = null, minimumRevision = selected.revision): CreditEvidenceHistory {
  const root = creditEvidence(selected, account, selected.kind), raw = object(value, ['items', 'next_before'])
  if (before !== null) revision(before)
  if (revision(minimumRevision) < root.revision) invalid()
  if (!Array.isArray(raw.items) || raw.items.length > CREDIT_PAGE_SIZE) invalid()
  const items = raw.items.map(value => creditEvidence(value, account, root.kind)), next = nullable(raw.next_before, revision)
  if (!items.length) { if (before !== 1 || next !== null) invalid(); return { items, next_before: null } }
  const first = items[0]!
  if (before === null ? first.revision < minimumRevision || !first.is_latest_revision : first.revision !== before - 1 || first.is_latest_revision) invalid()
  items.forEach((item, index) => {
    if (item.id !== root.id || item.source_id !== root.source_id || item.account_state !== first.account_state || index > 0 && (item.revision !== items[index - 1]!.revision - 1 || item.is_latest_revision) || item.revision === root.revision && !sameRetained(item, root)) invalid()
  })
  const last = items.at(-1)!
  if (last.revision === 1 ? next !== null : items.length !== CREDIT_PAGE_SIZE || next !== last.revision) invalid()
  return { items, next_before: next }
}
export function creditEvidenceInspection(value: unknown, account: CreditAccount, selected: CreditEvidence): CreditEvidence {
  const root = creditEvidence(selected, account, selected.kind), result = creditEvidence(value, account, root.kind)
  if (!sameRetained(result, root) || !root.is_latest_revision && result.is_latest_revision) invalid()
  return result
}
export function creditCashLabel(value: CreditCash | null, masked: boolean): string {
  if (masked) return '••••'
  if (value === null) return 'Not supplied as a separate amount'
  if (value.source === null) return `${value.currency} unavailable · ${value.missing_reason!.replaceAll('_', ' ')}`
  const [whole, fraction] = value.source.split('.')
  return `${value.currency} ${whole!.replace(/\B(?=(\d{3})+(?!\d))/g, ',')}${fraction === undefined ? '' : `.${fraction}`}`
}
export const creditKindNames = { statement: 'Statement evidence', current: 'Dated current reports', entry: 'Entry evidence' } as const
export const creditRoleNames = { posted_debit: 'Posted debit', posted_credit: 'Posted credit', pending_debit: 'Pending debit', pending_credit: 'Pending credit', unresolved: 'Unresolved direction' } as const
export const creditTreatmentNames = { movement: 'Supported movement interpretation', ambiguous: 'Ambiguous interpretation', unsupported: 'Unsupported interpretation' } as const
