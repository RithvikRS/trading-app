import { bankOwners, defaultBankingFilters, sampleRefunds } from './banking'
import type { BankCategory, BankTransaction, BankingFilters } from './banking'
import { sum } from './money'
import type { Classification, TransferState } from './transfers'

export const expenseCategories: readonly BankCategory[] = ['groceries', 'dining', 'shopping', 'utilities', 'housing', 'transport', 'health', 'subscriptions', 'fee', 'other-expense']
export const incomeCategories: readonly BankCategory[] = ['salary', 'interest', 'other-income']
export type CategoryTarget = BankCategory | 'suggested'
export type CategoryStatus = 'needs-review' | 'suggested' | 'reviewed' | 'all'
export type CategoryModel = Pick<TransferState, 'pairs' | 'classifications'>
export interface CategoryEdit { id: string; before?: Classification; after: Classification; from: Classification; source: string }
export interface CategoryPreview { ids: string[]; target: CategoryTarget; edits: CategoryEdit[]; excluded: { id: string; reason: string }[] }
export interface CategoryControls { status: CategoryStatus; filters: BankingFilters; ids: string[]; target: CategoryTarget; preview: CategoryPreview | null }
export const initialCategoryControls: CategoryControls = { status: 'needs-review', filters: defaultBankingFilters, ids: [], target: 'suggested', preview: null }
export const categoryStatusLabels: Record<CategoryStatus, string> = { 'needs-review': 'Needs review', suggested: 'Suggestions', reviewed: 'Reviewed', all: 'All records' }

// Deliberately supplied sample evidence, never inferred from arbitrary bank narration.
const suggestions: Readonly<Record<string, { category: BankCategory; reason: string }>> = {
  t05: { category: 'dining', reason: 'The bundled café receipt identifies food and drink. Confirm it or choose another category.' },
  t06: { category: 'dining', reason: 'A separate bundled café receipt supports Dining. This repeated payment is a separate record.' },
  t13: { category: 'shopping', reason: 'The bundled sample receipt identifies household supplies; the bank supplied no category.' },
}
export function categorySuggestion(item: BankTransaction, state: CategoryModel) {
  return state.classifications[item.id] || categoryRestriction(item, state) ? null : suggestions[item.id] ?? null
}
function paired(item: BankTransaction, state: CategoryModel) { return state.pairs.some(pair => pair.debitId === item.id || pair.creditId === item.id) }
function knownOwner(item: BankTransaction) { return Object.hasOwn(bankOwners, item.accountId) && bankOwners[item.accountId] === item.ownerId }
export function categoryOptions(item: BankTransaction): readonly BankCategory[] { return [...(item.direction === 'debit' ? expenseCategories : incomeCategories), 'unresolved'] }
export function categoryRestriction(item: BankTransaction, state: CategoryModel) {
  if (!knownOwner(item) || item.amount.minor <= 0n) return 'Source ownership or amount needs review.'
  if (item.status !== 'posted') return 'Pending record. Review its category after posting.'
  if (paired(item, state)) return 'Unlink the transfer pair before changing this classification.'
  if (item.sourceCategory === 'investment') return 'Investment funding is a separate role, excluded from spending.'
  if (item.sourceCategory === 'refund') return 'A verified refund follows its original purchase category. Review the purchase to change it.'
  return null
}
export function underlyingClassification(item: BankTransaction, state: CategoryModel): Classification {
  return state.classifications[item.id] ?? { category: item.sourceCategory === 'transfer' ? 'unresolved' : item.sourceCategory, provenance: 'source' }
}
export function refundEvidence(item: BankTransaction, records: readonly BankTransaction[], state: CategoryModel) {
  const evidence = sampleRefunds.find(link => link.creditId === item.id)
  const purchase = evidence && records.find(record => record.id === evidence.purchaseId)
  if (!evidence || item.sourceCategory !== 'refund' || item.direction !== 'credit' || item.status !== 'posted' || !knownOwner(item) || item.amount.minor <= 0n
    || !purchase || purchase.status !== 'posted' || purchase.direction !== 'debit' || !knownOwner(purchase) || purchase.ownerId !== item.ownerId || purchase.accountId !== item.accountId
    || purchase.amount.currency !== item.amount.currency || purchase.amount.minor < item.amount.minor || paired(purchase, state) || paired(item, state)) return null
  const classification = underlyingClassification(purchase, state)
  return expenseCategories.includes(classification.category) ? { purchase, category: classification.category } : null
}
export function baseClassification(item: BankTransaction, records: readonly BankTransaction[], state: CategoryModel): Classification {
  if (item.sourceCategory === 'refund') return refundEvidence(item, records, state) ? { category: 'refund', provenance: 'source' } : { category: 'unresolved', provenance: 'incomplete' }
  return underlyingClassification(item, state)
}
export function categorySourceKey(item: BankTransaction) {
  return [item.id, item.accountId, item.ownerId, item.sourceId, item.date, item.direction, item.amount.currency, item.amount.minor.toString(), item.status, item.sourceCategory].join('|')
}
export function sameClassification(left: Classification | undefined, right: Classification | undefined) { return left?.category === right?.category && left?.provenance === right?.provenance }
export function previewCategories(ids: readonly string[], target: CategoryTarget, records: readonly BankTransaction[], state: CategoryModel): CategoryPreview {
  const preview: CategoryPreview = { ids: [...new Set(ids)], target, edits: [], excluded: [] }
  for (const id of preview.ids) {
    const item = records.find(record => record.id === id)
    const restriction = item ? categoryRestriction(item, state) : 'Source record is unavailable.'
    if (!item || restriction) { preview.excluded.push({ id, reason: restriction! }); continue }
    const suggestion = categorySuggestion(item, state)
    const category = target === 'suggested' ? suggestion?.category : target
    if (!category || !categoryOptions(item).includes(category)) { preview.excluded.push({ id, reason: target === 'suggested' ? 'No unreviewed suggestion is available.' : 'The selected category does not fit this record’s direction or role.' }); continue }
    const before = state.classifications[id]
    const after: Classification = { category, provenance: target === 'suggested' ? 'suggestion' : 'manual' }
    if (sameClassification(before, after)) { preview.excluded.push({ id, reason: 'This review decision is already applied.' }); continue }
    preview.edits.push({ id, before, after, from: baseClassification(item, records, state), source: categorySourceKey(item) })
  }
  return preview
}

// Scope controls which booked entries contribute; full records supply refund evidence.
export function classifiedSpending(scope: readonly BankTransaction[], records: readonly BankTransaction[], state: CategoryModel, classify: (item: BankTransaction) => Classification) {
  const posted = scope.filter(item => item.status === 'posted')
  const gross = sum(posted.filter(item => item.direction === 'debit' && expenseCategories.includes(classify(item).category)).map(item => item.amount))
  const refunds = sum(posted.filter(item => classify(item).category === 'refund' && refundEvidence(item, records, state)).map(item => item.amount))
  const unresolved = posted.filter(item => classify(item).category === 'unresolved')
  return { gross, refunds, net: { ...gross, minor: gross.minor - refunds.minor },
    outgoing: sum(unresolved.filter(item => item.direction === 'debit').map(item => item.amount)), incoming: sum(unresolved.filter(item => item.direction === 'credit').map(item => item.amount)), unresolved: unresolved.length }
}
