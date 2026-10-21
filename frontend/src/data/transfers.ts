import { bankOwners, sampleTransfer } from './banking'
import type { BankCategory, BankReview, BankTransaction } from './banking'
import { sum } from './money'
import { baseClassification, categoryOptions, categoryRestriction, categorySourceKey, previewCategories, sameClassification } from './categories'
import type { CategoryEdit, CategoryPreview } from './categories'

export type TransferPair = Readonly<{ id: string; debitId: string; creditId: string }>
export type Classification = Readonly<{ category: BankCategory; provenance: 'source' | 'manual' | 'suggestion' | 'transfer' | 'incomplete' }>
type PairChange = Readonly<{ kind: 'confirm' | 'dismiss' | 'restore' | 'unlink'; pair: TransferPair; label: string }>
export type ReviewChange = PairChange | Readonly<{ kind: 'category'; edits: readonly CategoryEdit[]; label: string }>
export interface TransferState {
  pairs: readonly TransferPair[]; dismissed: readonly TransferPair[]
  // Underlying classifications remain intact when a transfer overlay is added or removed.
  classifications: Readonly<Record<string, Classification>>
  history: readonly ReviewChange[]; message: string; error: boolean
}
export type TransferAction = { type: 'confirm' | 'dismiss' | 'restore' | 'unlink'; pair: TransferPair } | { type: 'undo' } | { type: 'reset' } | { type: 'categorize'; preview: CategoryPreview }
export type TransferStatus = 'suggested' | 'ambiguous' | 'unmatched' | 'confirmed' | 'dismissed'
export interface TransferControls { view: 'activity' | 'transfers' | 'categories'; status: TransferStatus; selected: string | null }
export const initialTransferControls: TransferControls = { view: 'activity', status: 'suggested', selected: null }
export const transferLabels: Record<TransferStatus, string> = { suggested: 'Suggested', ambiguous: 'Ambiguous', unmatched: 'Unmatched', confirmed: 'Confirmed', dismissed: 'Dismissed' }

export function pairId(debitId: string, creditId: string) { return debitId === sampleTransfer.debitId && creditId === sampleTransfer.creditId ? sampleTransfer.id : `pair-${debitId}-${creditId}` }
export function createTransferState(withSample = true): TransferState {
  return { pairs: withSample ? [{ ...sampleTransfer }] : [], dismissed: [], classifications: {}, history: [], message: '', error: false }
}
function calendarDay(date: string) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) return null
  const timestamp = Date.parse(`${date}T00:00:00Z`)
  return Number.isFinite(timestamp) && new Date(timestamp).toISOString().slice(0, 10) === date ? timestamp / 86_400_000 : null
}
export function eligibleRecord(item: BankTransaction) {
  return Object.hasOwn(bankOwners, item.accountId) && item.ownerId === bankOwners[item.accountId]
    && item.status === 'posted' && item.amount.minor > 0n && (item.sourceCategory === 'unresolved' || item.sourceCategory === 'transfer') && calendarDay(item.date) !== null
}
export function eligiblePair(debit: BankTransaction, credit: BankTransaction) {
  const left = calendarDay(debit.date), right = calendarDay(credit.date)
  return eligibleRecord(debit) && eligibleRecord(credit) && debit.id !== credit.id && debit.accountId !== credit.accountId && debit.ownerId === credit.ownerId
    && debit.direction === 'debit' && credit.direction === 'credit' && debit.amount.currency === credit.amount.currency && debit.amount.minor === credit.amount.minor
    && left !== null && right !== null && Math.abs(left - right) <= 3
}
export function pairRecords(pair: TransferPair, records: readonly BankTransaction[]) {
  const debit = records.find(item => item.id === pair.debitId), credit = records.find(item => item.id === pair.creditId)
  return debit && credit && eligiblePair(debit, credit) ? { debit, credit } : null
}
function hasLeg(pair: TransferPair, id: string) { return pair.debitId === id || pair.creditId === id }
function conflicts(pair: TransferPair, pairs: readonly TransferPair[]) { return pairs.some(other => hasLeg(other, pair.debitId) || hasLeg(other, pair.creditId)) }
export function confirmedPairs(records: readonly BankTransaction[], state: TransferState) { return state.pairs.filter(pair => pairRecords(pair, records)) }
export function effectiveClassification(item: BankTransaction, records: readonly BankTransaction[], state: TransferState): Classification {
  const pair = state.pairs.find(pair => hasLeg(pair, item.id))
  if (pair) return pairRecords(pair, records) ? { category: 'transfer', provenance: 'transfer' } : { category: 'unresolved', provenance: 'incomplete' }
  return baseClassification(item, records, state)
}
export function transferReviewStatus(item: BankTransaction, records: readonly BankTransaction[], state: TransferState): BankReview {
  const classification = effectiveClassification(item, records, state)
  return classification.provenance === 'transfer' ? 'confirmed' : classification.category === 'unresolved' ? 'needs-review' : classification.provenance === 'manual' || classification.provenance === 'suggestion' ? 'reviewed' : 'recorded'
}
export function transferQueue(records: readonly BankTransaction[], state: TransferState) {
  const available = records.filter(item => eligibleRecord(item) && !state.pairs.some(pair => hasLeg(pair, item.id)))
  const all: TransferPair[] = []
  for (const debit of available.filter(item => item.direction === 'debit')) for (const credit of available.filter(item => item.direction === 'credit')) {
    if (eligiblePair(debit, credit)) all.push({ id: pairId(debit.id, credit.id), debitId: debit.id, creditId: credit.id })
  }
  all.sort((a, b) => a.id.localeCompare(b.id))
  const candidates = all.filter(pair => !state.dismissed.some(dismissed => dismissed.id === pair.id))
  const competing = (pair: TransferPair) => candidates.some(other => other.id !== pair.id && (hasLeg(other, pair.debitId) || hasLeg(other, pair.creditId)))
  return {
    suggested: candidates.filter(pair => !competing(pair)), ambiguous: candidates.filter(competing),
    unmatched: available.filter(item => !all.some(pair => hasLeg(pair, item.id))),
    confirmed: confirmedPairs(records, state), dismissed: state.dismissed,
    incomplete: state.pairs.filter(pair => !pairRecords(pair, records)),
  }
}
export function transferCoverage(records: readonly BankTransaction[], state: TransferState) {
  const unresolved = records.filter(item => item.status === 'posted' && effectiveClassification(item, records, state).category === 'unresolved')
  const pairs = confirmedPairs(records, state)
  return { unresolved: unresolved.length, debits: sum(unresolved.filter(item => item.direction === 'debit').map(item => item.amount)), credits: sum(unresolved.filter(item => item.direction === 'credit').map(item => item.amount)),
    confirmed: pairs.length, transferred: sum(pairs.map(pair => records.find(item => item.id === pair.debitId)!.amount)) }
}

const labels: Record<PairChange['kind'], string> = { confirm: 'Pair confirmed', dismiss: 'Candidate dismissed', restore: 'Candidate restored', unlink: 'Pair unlinked' }
function result(state: TransferState, message: string, error = false) { return { ...state, message, error } }
export function changeTransfers(state: TransferState, action: TransferAction, records: readonly BankTransaction[]): TransferState {
  if (action.type === 'categorize') {
    const preview = previewCategories(action.preview.ids, action.preview.target, records, state)
    if (JSON.stringify(preview) !== JSON.stringify(action.preview)) return result(state, 'The preview is out of date. Review the current records before applying any changes.', true)
    if (!preview.edits.length) return result(state, 'No eligible category changes to apply. Source records are unchanged.')
    const classifications = { ...state.classifications }
    for (const edit of preview.edits) classifications[edit.id] = { ...edit.after }
    return { ...state, classifications, history: [...state.history, { kind: 'category', edits: preview.edits, label: 'Categories updated' }], message: `${preview.edits.length} category decision${preview.edits.length === 1 ? '' : 's'} applied. ${preview.excluded.length} excluded. Source records and balances are unchanged.`, error: false }
  }
  if (action.type === 'reset') {
    const initial = createTransferState()
    return { ...initial, pairs: initial.pairs.filter(pair => pairRecords(pair, records)), message: 'Sample decisions reset. Review history cleared.' }
  }
  if (action.type === 'undo') {
    // Skip inverses that require an unavailable or now-occupied source record.
    for (let index = state.history.length - 1; index >= 0; index--) {
      const change = state.history[index]!
      if (change.kind === 'category') {
        const applicable = change.edits.every(edit => {
          const item = records.find(record => record.id === edit.id)
          return item && categorySourceKey(item) === edit.source && !categoryRestriction(item, state) && sameClassification(state.classifications[edit.id], edit.after) && (!edit.before || categoryOptions(item).includes(edit.before.category))
        })
        if (!applicable) continue
        const classifications = { ...state.classifications }
        for (const edit of change.edits) { if (edit.before) classifications[edit.id] = { ...edit.before }; else delete classifications[edit.id] }
        return { ...state, classifications, history: state.history.filter((_, i) => i !== index), message: 'Category changes undone together. Linked refunds follow the restored purchase categories.', error: false }
      }
      const pair = change.pair
      let pairs = state.pairs, dismissed = state.dismissed
      if (change.kind === 'confirm') {
        if (!pairs.some(item => item.id === pair.id)) continue
        pairs = pairs.filter(item => item.id !== pair.id)
      } else if (change.kind === 'unlink') {
        if (!pairRecords(pair, records) || conflicts(pair, pairs)) continue
        pairs = [...pairs, pair]
      } else if (change.kind === 'dismiss') {
        if (!dismissed.some(item => item.id === pair.id)) continue
        dismissed = dismissed.filter(item => item.id !== pair.id)
      } else {
        if (dismissed.some(item => item.id === pair.id)) continue
        dismissed = [...dismissed, pair]
      }
      return { ...state, pairs, dismissed, history: state.history.filter((_, i) => i !== index), message: `${change.label} undone. Both source records are unchanged.`, error: false }
    }
    return result(state, 'No change can be undone with the available source records. Restore the sample data or reset decisions.', true)
  }
  const pair = action.pair
  if (pair.id !== pairId(pair.debitId, pair.creditId)) return result(state, 'This pair is no longer valid. Review the current candidates.', true)
  let pairs = state.pairs, dismissed = state.dismissed
  if (action.type === 'confirm') {
    if (pairs.some(item => item.id === pair.id)) return pairRecords(pair, records) ? result(state, 'This pair is already confirmed.') : result(state, 'This pair has incomplete source coverage. Restore the records or unlink it before reviewing again.', true)
    if (!pairRecords(pair, records) || conflicts(pair, pairs) || dismissed.some(item => item.id === pair.id)) return result(state, 'This pair is no longer eligible. A record may be unavailable, dismissed, or already matched. Review the current candidates.', true)
    pairs = [...pairs, { ...pair }]
  } else if (action.type === 'dismiss') {
    if (dismissed.some(item => item.id === pair.id)) return result(state, 'This candidate is already dismissed.')
    if (!pairRecords(pair, records) || conflicts(pair, pairs)) return result(state, 'This candidate is no longer available to dismiss.', true)
    dismissed = [...dismissed, { ...pair }]
  } else if (action.type === 'restore') {
    if (!dismissed.some(item => item.id === pair.id)) return result(state, 'This candidate is already restored.')
    dismissed = dismissed.filter(item => item.id !== pair.id)
  } else {
    if (!pairs.some(item => item.id === pair.id)) return result(state, 'This pair is already unlinked.')
    pairs = pairs.filter(item => item.id !== pair.id)
  }
  return { ...state, pairs, dismissed, history: [...state.history, { kind: action.type, pair: { ...pair }, label: labels[action.type] }],
    message: `${labels[action.type]}. ${action.type === 'confirm' ? 'Both records are classified as an internal transfer.' : action.type === 'unlink' ? 'Both records return to their previous classifications.' : 'Other candidates and source records are unchanged.'}`, error: false }
}
