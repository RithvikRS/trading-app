import { nativeGroups, normalizeImportRow, previewImport } from './imports'
import type { ImportBatch, ImportId, IncomingRow, PreviewRow } from './imports'
import type { Money } from './money'

export type ImportChoice = 'include' | 'skip' | 'exclude'
export const choiceLabels = { include: 'Included candidate', skip: 'Skipped duplicate', exclude: 'Excluded from review' } as const
export interface ImportDecision {
  choice: ImportChoice; evidence: string; reason: string; original: IncomingRow
  matches: IncomingRow[]; previous: ImportChoice | null
}
export interface ImportReceipt {
  key: string; confirmationToken: string; revision: string; counts: ReviewCounts; reasons: string[]
  groups: ReturnType<typeof nativeGroups>['groups']; difference: Money | null
}
interface BatchReview { decisions: Record<string, ImportDecision>; aside: boolean; receipt: ImportReceipt | null }
type Reviews = Partial<Record<ImportId, BatchReview>>
interface HistoryEntry { before: Reviews; batch: ImportId; label: string }
export interface ImportReviewState { batches: Reviews; history: HistoryEntry[]; serial: number; message: string }
interface ReviewCounts { included: number; present: number; excluded: number; unresolved: number }
export type ImportOperation = { type: 'row'; rowId: string; choice: ImportChoice | 'restore' } | { type: 'suggestions' | 'complete' | 'aside' | 'reopen' }
export interface ImportProposal { batchId: ImportId; token: string; operation: ImportOperation }
export const createImportReviewState = (): ImportReviewState => ({ batches: {}, history: [], serial: 0, message: '' })
const initialBatch = (): BatchReview => ({ decisions: {}, aside: false, receipt: null })
export const batchReview = (state: ImportReviewState, id: ImportId) => state.batches[id] ?? initialBatch()
// In-memory evidence comparison, not a file hash, credential, or durable idempotency key.
const serialize = (value: unknown) => JSON.stringify(value, (_key, item: unknown) => typeof item === 'bigint' ? item.toString() : item)
const evidence = (batch: ImportBatch) => serialize(batch)
const identity = (row: IncomingRow) => serialize([row.original.provider, row.original.owner, row.original.account, row.original.transactionId])
const cloneRow = (row: IncomingRow): IncomingRow => ({ id: row.id, original: { ...row.original } })

export function distinctEvidence(batch: ImportBatch, item: PreviewRow): string | null {
  if (item.disposition !== 'overlap' || !item.matches.length) return null
  const reasons: string[] = []
  for (const match of item.matches) {
    const proof = batch.distinctPairs?.find(pair => pair.incomingId === item.row.id && pair.baselineId === match.id)
    if (!proof || identity(match) === identity(item.row) || match.original.reference === item.row.original.reference) return null
    reasons.push(proof.reason)
  }
  return reasons.join(' ')
}
export function permittedChoices(batch: ImportBatch, item: PreviewRow): ImportChoice[] {
  if (item.disposition === 'new' || distinctEvidence(batch, item)) return ['include', 'exclude']
  if (item.disposition === 'present' || item.disposition === 'duplicate') return ['skip', 'exclude']
  return ['exclude']
}
function reasonFor(batch: ImportBatch, item: PreviewRow, choice: ImportChoice) {
  return choice === 'exclude' ? 'Set aside for further source review; required evidence and financial blockers remain.'
    : choice === 'skip' ? item.disposition === 'present' ? 'Exact scoped source identity and immutable fields already exist in the comparison baseline.' : 'Exact repeated incoming occurrence; the canonical source identity contributes at most once.'
      : distinctEvidence(batch, item) ?? 'Valid unique candidate with a known source account and owner.'
}
function validDecision(batch: ImportBatch, item: PreviewRow, decision?: ImportDecision): decision is ImportDecision {
  return Boolean(decision && decision.evidence === evidence(batch) && permittedChoices(batch, item).includes(decision.choice))
}

export function reviewImport(batch: ImportBatch, state: ImportReviewState) {
  const current = batchReview(state, batch.id), source = previewImport(batch)
  const counts: ReviewCounts = { included: 0, present: 0, excluded: 0, unresolved: 0 }
  const included: PreviewRow[] = [], blockers: string[] = [], reasons: string[] = []
  const rows = source.rows.map(item => {
    const decision = current.decisions[item.row.id], valid = validDecision(batch, item, decision)
    const status = !decision ? 'Needs decision' : !valid ? 'Needs review · Evidence changed' : choiceLabels[decision.choice]
    if (!valid) counts.unresolved++
    else if (decision.choice === 'include') { counts.included++; included.push(item) }
    else if (decision.choice === 'skip' && item.disposition === 'present') counts.present++
    else counts.excluded++
    if (valid) reasons.push(`${item.row.id}: ${reasonFor(batch, item, decision.choice)}`)
    return { ...item, decision, valid, status }
  })
  if (Object.keys(current.decisions).some(id => !rows.some(row => row.row.id === id))) blockers.push('Previously reviewed rows are missing from this revision. Reset reviews and inspect the new source.')
  if (counts.unresolved) blockers.push('Every incoming occurrence needs a compatible review decision.')
  if (source.rows.some(row => row.disposition === 'invalid' || row.disposition === 'conflict')) blockers.push('Invalid fields, unsupported records, or conflicting source identities remain unresolved, even when excluded.')
  if (!batch.complete) blockers.push('Complete coverage for the supplied statement period is unavailable.')
  if (!batch.opening || !batch.closing || batch.opening.currency !== batch.currency || batch.closing.currency !== batch.currency) blockers.push('Compatible native opening and closing balances are required.')
  if (source.reconciliation.status !== 'matches') blockers.push('Original source arithmetic is unavailable or has an unexplained difference.')

  const baseline: PreviewRow[] = batch.baseline.rows.map(row => ({ row, normalized: normalizeImportRow(row, batch), disposition: 'present', reasons: [], matches: [], canonicalId: null }))
  const baselineKeys = new Set(baseline.map(item => identity(item.row)))
  const baselineValid = baselineKeys.size === baseline.length && baseline.every(item => !item.normalized.issues.length)
  if (!baselineValid) blockers.push('Comparison baseline identity, account, currency, or period is incompatible. A fresh preview is required.')
  const combined = [...baseline, ...included]
  const unique = new Map(combined.map(item => [identity(item.row), item]))
  if (unique.size !== combined.length) blockers.push('Proposed records repeat an existing scoped identity.')
  // Check coverage independently of the net balance: equal opposite omissions must not cancel out.
  if (rows.some(item => !unique.has(identity(item.row)))) blockers.push('Necessary source records are omitted from the retained baseline and proposed candidates.')
  if (rows.some(item => item.valid && item.decision?.choice === 'skip' && item.disposition === 'duplicate' && !rows.some(canonical => canonical.row.id === item.canonicalId && canonical.valid && (canonical.decision?.choice === 'include' || canonical.disposition === 'present' && canonical.decision?.choice === 'skip')))) blockers.push('A skipped copy requires its canonical incoming row to be included or matched to the baseline.')
  const retained = nativeGroups([...unique.values()]), proposed = nativeGroups(included)
  const nativeValid = baselineValid && retained.unreadable === 0 && retained.groups.every(group => group.currency === batch.currency)
  const posted = retained.groups.find(group => group.status === 'posted' && group.currency === batch.currency)
  const computed = nativeValid && batch.opening?.currency === batch.currency ? { currency: batch.currency, minor: batch.opening.minor + (posted?.net.minor ?? 0n) } : null
  const difference = computed && batch.closing?.currency === batch.currency ? { currency: batch.currency, minor: batch.closing.minor - computed.minor } : null
  if (!difference || difference.minor !== 0n) blockers.push('Retained baseline plus unique candidates does not reconcile to the supplied closing balance.')
  const key = serialize([evidence(batch), Object.entries(current.decisions).sort(([a], [b]) => a.localeCompare(b))])
  const receipt = current.receipt?.key === key && !blockers.length ? current.receipt : null
  if (current.receipt && !receipt) blockers.push('The previous completion is incompatible with current evidence. Reopen and inspect it again.')
  return { rows, counts, blockers, reasons, proposed, retained, computed, difference, key, receipt, aside: current.aside, ready: blockers.length === 0 && !current.aside }
}

export function proposeImport(batch: ImportBatch, state: ImportReviewState, operation: ImportOperation): ImportProposal {
  return { batchId: batch.id, operation, token: serialize([evidence(batch), state.serial, batchReview(state, batch.id), operation]) }
}
export function changeImportReview(state: ImportReviewState, batch: ImportBatch, proposal: ImportProposal, visible = true): ImportReviewState {
  const fail = (message: string) => ({ ...state, message })
  const current = batchReview(state, batch.id), operation = proposal.operation
  if (!['row', 'suggestions', 'complete', 'aside', 'reopen'].includes(operation.type)) return fail('Unsupported review action. Nothing was applied.')
  if (!visible) return fail('Show amounts and load the sample before changing its review.')
  // A repeated confirmation of an already completed identical review is a no-op.
  if (operation.type === 'complete' && reviewImport(batch, state).receipt && proposal.batchId === batch.id && proposal.token === current.receipt?.confirmationToken) return state
  if (proposal.batchId !== batch.id || proposal.token !== proposeImport(batch, state, operation).token) return fail('Evidence or decisions changed. Open a fresh review preview; nothing was applied.')
  if ((current.aside || current.receipt) && operation.type !== 'reopen' && operation.type !== 'complete') return fail('Reopen this sample review before changing decisions.')
  let next: BatchReview = { ...current, decisions: { ...current.decisions }, receipt: null }
  let label: string = operation.type
  const preview = previewImport(batch)
  function decide(item: PreviewRow, choice: ImportChoice) {
    next.decisions[item.row.id] = { choice, evidence: evidence(batch), reason: reasonFor(batch, item, choice), original: cloneRow(item.row), matches: [...item.matches, ...preview.rows.filter(row => row.row.id === item.canonicalId).map(row => row.row)].map(cloneRow), previous: current.decisions[item.row.id]?.choice ?? null }
  }
  if (operation.type === 'row') {
    const item = preview.rows.find(row => row.row.id === operation.rowId)
    if (!item) return fail('This row is unavailable. Nothing was applied.')
    if (operation.choice === 'restore') { if (!current.decisions[item.row.id]) return state; delete next.decisions[item.row.id] }
    else { if (!permittedChoices(batch, item).includes(operation.choice)) return fail('This choice is not supported by the supplied evidence. Nothing was applied.'); decide(item, operation.choice) }
    label = `${operation.rowId} · ${operation.choice === 'restore' ? 'Decision restored' : choiceLabels[operation.choice]}`
  } else if (operation.type === 'suggestions') {
    for (const item of preview.rows) {
      if (current.decisions[item.row.id]) continue
      if (item.disposition === 'new') decide(item, 'include')
      else if (item.disposition === 'present' || item.disposition === 'duplicate') decide(item, 'skip')
    }
    if (serialize(next.decisions) === serialize(current.decisions)) return state
    label = 'Applied eligible suggested choices'
  } else if (operation.type === 'complete') {
    const review = reviewImport(batch, state)
    if (review.receipt) return state
    if (!review.ready) return fail('Completion is blocked by unresolved evidence. No receipt was created.')
    next.receipt = { key: review.key, confirmationToken: proposal.token, revision: batch.revision, counts: { ...review.counts }, reasons: [...review.reasons], groups: review.proposed.groups, difference: review.difference }
    label = 'Completed sample review · No records saved'
  } else if (operation.type === 'aside') { next.aside = true; label = 'Set sample aside' }
  else { next.aside = false; label = 'Reopened sample review' }
  return { batches: { ...state.batches, [batch.id]: next }, history: [...state.history, { before: state.batches, batch: batch.id, label }], serial: state.serial + 1, message: label }
}
export function undoImportReview(state: ImportReviewState): ImportReviewState {
  const last = state.history.at(-1)
  return last ? { batches: last.before, history: state.history.slice(0, -1), serial: state.serial + 1, message: `Undid review change in ${last.batch}.` } : state
}
export function resetImportReviews(state: ImportReviewState): ImportReviewState {
  return { ...createImportReviewState(), serial: state.serial + 1, message: 'Sample import reviews reset. Other workspace reviews are unchanged.' }
}
