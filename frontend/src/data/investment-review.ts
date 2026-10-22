import { getHoldings, UNIT_SCALE } from './holdings'
import type { Money } from './money'
import { investmentDecimal, investmentEvidence, investmentIdentity, investmentSources, normalizeInvestment, previewInvestment } from './investment-imports'
import type { InvestmentAccount, InvestmentBatch, InvestmentImportId, InvestmentPreviewRow, InvestmentRow } from './investment-imports'
import type { ImportReviewState } from './import-review'

export const investmentChoices = { include: 'Include candidate', skip: 'Skip as duplicate', exclude: 'Exclude from this sample review', incoming: 'Use incoming snapshot', existing: 'Keep comparison snapshot' } as const
export type InvestmentChoice = keyof typeof investmentChoices
interface InvestmentDecision { choice: InvestmentChoice; evidence: string; reason: string; original: InvestmentRow; matches: InvestmentRow[]; previous: InvestmentChoice | null }
interface Counts { included: number; present: number; excluded: number; unresolved: number }
export interface InvestmentReceipt { key: string; token: string; revision: string; scope: string; counts: Counts; reasons: string[]; groups: InvestmentMoneyGroup[] }
export interface InvestmentBatchReview { decisions: Record<string, InvestmentDecision>; aside: boolean; receipt: InvestmentReceipt | null }
export type InvestmentReviews = Partial<Record<InvestmentImportId, InvestmentBatchReview>>
export type InvestmentOperation = { type: 'row'; rowId: string; choice: InvestmentChoice | 'restore' } | { type: 'suggestions' | 'complete' | 'aside' | 'reopen' }
export interface InvestmentProposal { batchId: InvestmentImportId; operation: InvestmentOperation; token: string }
export interface InvestmentMoneyGroup { label: string; currency: Money['currency']; value: Money; count: number; missing: number }
export interface InvestmentCheck { label: string; kind: 'units' | 'money'; expected: bigint | null; actual: bigint | null; currency?: Money['currency']; passed: boolean }
const initial = (): InvestmentBatchReview => ({ decisions: {}, aside: false, receipt: null })
export const investmentBatchReview = (state: ImportReviewState, id: InvestmentImportId) => state.investments[id] ?? initial()
const copy = (row: InvestmentRow): InvestmentRow => ({ id: row.id, original: { ...row.original } })
export function permittedInvestmentChoices(item: InvestmentPreviewRow): InvestmentChoice[] {
  return item.disposition === 'new' ? ['include', 'exclude'] : item.disposition === 'overlap' ? ['incoming', 'existing', 'exclude'] : item.disposition === 'present' || item.disposition === 'duplicate' ? ['skip', 'exclude'] : ['exclude']
}
function reason(item: InvestmentPreviewRow, choice: InvestmentChoice) {
  if (choice === 'exclude') return 'Set aside for source review. Necessary evidence, identity, and reconciliation blockers remain.'
  if (choice === 'incoming' || choice === 'existing') return 'One version of the same position and snapshot instant; preference is limited to this identity and date. No extra position or units are added.'
  if (choice === 'skip') return item.canonicalId ? 'Repeated occurrence; retain its canonical identity once.' : 'The exact scoped record already exists in the isolated comparison.'
  return 'Selected as a unique typed source record. Snapshots, activity, cash, and lots keep separate meanings.'
}

function checks(batch: InvestmentBatch, records: InvestmentRow[]): InvestmentCheck[] {
  const rows = records.map(row => ({ row, normalized: normalizeInvestment(row, batch) }))
  const result: InvestmentCheck[] = []
  for (const checkpoint of batch.positions) {
    const matched = rows.filter(item => item.normalized.holding?.id === checkpoint.holdingId)
    const positions = matched.filter(item => item.normalized.kind === 'position' && item.row.original.snapshotAt === checkpoint.snapshotAt)
    const expected = investmentDecimal(checkpoint.units, UNIT_SCALE), actual = positions.length === 1 ? positions[0]!.normalized.units : null
    const holding = getHoldings().find(item => item.id === checkpoint.holdingId)
    const name = holding ? `${holding.instrument.name} · ${investmentSources[holding.accountId as InvestmentAccount]}${holding.instrument.plan ? ` · ${holding.instrument.plan} / ${holding.instrument.option}` : ''}` : 'Unknown position'
    const label = `${name} · Supplied position units`
    result.push({ label, kind: 'units', expected, actual, passed: expected !== null && actual === expected })
    if (batch.mode !== 'snapshot' && (batch.rows.some(row => normalizeInvestment(row, batch).holding?.id === checkpoint.holdingId) || matched.some(item => item.normalized.kind === 'activity'))) {
      const opening = checkpoint.opening === null ? null : investmentDecimal(checkpoint.opening, UNIT_SCALE)
      const events = matched.filter(item => item.normalized.kind === 'activity')
      const movement = events.every(item => !item.normalized.issues.length && item.normalized.units !== null) ? events.reduce((sum, item) => sum + item.normalized.units! * (item.row.original.event === 'purchase' ? 1n : -1n), 0n) : null
      const closing = opening !== null && movement !== null ? opening + movement : null
      result.push({ label: `${name} · Opening + activity = closing units`, kind: 'units', expected, actual: closing, passed: expected !== null && closing === expected && closing >= 0n })
      if (batch.mode === 'lots') {
        const lots = matched.filter(item => item.normalized.kind === 'lot')
        const remaining = lots.length && lots.every(item => !item.normalized.issues.length && item.normalized.units !== null) ? lots.reduce((sum, item) => sum + item.normalized.units!, 0n) : null
        result.push({ label: `${name} · Remaining lots = position units`, kind: 'units', expected, actual: remaining, passed: expected !== null && remaining === expected })
      }
    }
  }
  for (const checkpoint of batch.cash) {
    const matched = rows.filter(item => item.row.original.account === checkpoint.account && item.normalized.currency === checkpoint.currency)
    const balances = matched.filter(item => item.normalized.kind === 'cash' && item.row.original.event === 'balance' && item.row.original.snapshotAt === checkpoint.snapshotAt)
    const expected = investmentDecimal(checkpoint.closing, 2), actual = balances.length === 1 ? balances[0]!.normalized.amount?.minor ?? null : null
    result.push({ label: `${investmentSources[checkpoint.account]} · Supplied cash balance`, kind: 'money', currency: checkpoint.currency, expected, actual, passed: expected !== null && actual === expected })
    if (batch.mode !== 'snapshot') {
      const opening = checkpoint.opening === null ? null : investmentDecimal(checkpoint.opening, 2)
      const events = matched.filter(item => item.normalized.kind === 'activity' || item.normalized.kind === 'cash' && item.row.original.event === 'dividend')
      const movement = events.every(item => !item.normalized.issues.length) ? events.reduce((sum, item) => item.normalized.kind === 'cash' ? sum + item.normalized.net!.minor : sum + item.normalized.amount!.minor * (item.row.original.event === 'purchase' ? -1n : 1n) - item.normalized.fee!.minor, 0n) : null
      const closing = opening !== null && movement !== null ? opening + movement : null
      result.push({ label: `${investmentSources[checkpoint.account]} · Opening + cash activity = closing`, kind: 'money', currency: checkpoint.currency, expected, actual: closing, passed: expected !== null && closing === expected && closing >= 0n })
    }
  }
  return result
}
export function investmentMoneyGroups(batch: InvestmentBatch, records: InvestmentRow[]): InvestmentMoneyGroup[] {
  const groups: InvestmentMoneyGroup[] = []
  function add(label: string, currency: Money['currency'], value: Money | null) {
    let group = groups.find(item => item.label === label && item.currency === currency)
    if (!group) { group = { label, currency, value: { currency, minor: 0n }, count: 0, missing: 0 }; groups.push(group) }
    group.count++; if (value) group.value = { currency, minor: group.value.minor + value.minor }; else group.missing++
  }
  for (const raw of records) {
    const row = normalizeInvestment(raw, batch)
    if (!row.currency) continue
    if (row.kind === 'position') add('Marked position values', row.currency, row.value)
    if (row.kind === 'lot') { add('Source lot purchase amounts', row.currency, row.amount); add('Lot fees', row.currency, row.fee); add('Supplied tax basis', row.currency, row.basis) }
    if (row.kind === 'activity') { add(raw.original.event === 'purchase' ? 'Purchase cash outflow' : 'Sale cash inflow', row.currency, row.amount); add('Activity fees', row.currency, row.fee) }
    if (row.kind === 'cash' && raw.original.event === 'balance') add('Cash snapshots', row.currency, row.amount)
    if (row.kind === 'cash' && raw.original.event === 'dividend') { add('Gross cash dividends', row.currency, row.amount); add('Dividend withholding', row.currency, row.withholding); add('Net cash dividends', row.currency, row.net) }
  }
  return groups
}

export function reviewInvestment(batch: InvestmentBatch, state: ImportReviewState) {
  const current = investmentBatchReview(state, batch.id), evidence = investmentEvidence(batch), preview = previewInvestment(batch)
  const counts: Counts = { included: 0, present: 0, excluded: 0, unresolved: 0 }, blockers: string[] = [], reasons: string[] = []
  const retained = new Map(batch.baseline.rows.map(row => [investmentIdentity(row), row]))
  const baselineValid = retained.size === batch.baseline.rows.length && batch.baseline.rows.every(row => !normalizeInvestment(row, batch).issues.length)
  const rows = preview.map(item => {
    const decision = current.decisions[item.row.id]
    const valid = Boolean(decision && decision.evidence === evidence && permittedInvestmentChoices(item).includes(decision.choice))
    if (!valid || !decision) counts.unresolved++
    else {
      if (decision.choice === 'include' || decision.choice === 'incoming') { counts.included++; retained.set(investmentIdentity(item.row), item.row) }
      else if (decision.choice === 'existing' || decision.choice === 'skip' && item.disposition === 'present') counts.present++
      else counts.excluded++
      reasons.push(`${item.row.id}: ${reason(item, decision.choice)}`)
    }
    return { ...item, decision, valid, status: !decision ? 'Needs decision' : !valid ? 'Needs review · Evidence changed' : investmentChoices[decision.choice] }
  })
  if (counts.unresolved) blockers.push('Every incoming occurrence needs a compatible review choice.')
  if (Object.keys(current.decisions).some(id => !rows.some(item => item.row.id === id))) blockers.push('Previously reviewed rows are missing. Reset and inspect this revision again.')
  if (!baselineValid) blockers.push('Comparison identities or source scope are incompatible; a fresh preview is required.')
  if (rows.some(item => item.disposition === 'invalid' || item.disposition === 'conflict')) blockers.push('Invalid or conflicting source evidence remains blocked, even if excluded. Source preference cannot repair it.')
  if (!batch.complete) blockers.push('The declared review scope has incomplete supplied evidence.')
  const allEvidence = [...batch.rows, ...batch.baseline.rows].map(row => ({ row, normalized: normalizeInvestment(row, batch) }))
  if (allEvidence.some(item => item.normalized.holding && !batch.positions.some(checkpoint => checkpoint.holdingId === item.normalized.holding!.id && checkpoint.snapshotAt === item.row.original.snapshotAt) || item.normalized.kind === 'cash' && item.row.original.event === 'balance' && !batch.cash.some(checkpoint => checkpoint.account === item.row.original.account && checkpoint.currency === item.normalized.currency && checkpoint.snapshotAt === item.row.original.snapshotAt))) blockers.push('A source record lacks an independent position or cash checkpoint for its identity and date.')
  if (batch.mode !== 'snapshot' && allEvidence.some(item => (item.normalized.kind === 'activity' || item.normalized.kind === 'cash' && item.row.original.event === 'dividend') && !batch.cash.some(checkpoint => checkpoint.account === item.row.original.account && checkpoint.currency === item.normalized.currency && checkpoint.snapshotAt === item.row.original.snapshotAt))) blockers.push('Cash activity lacks an independent opening and closing cash checkpoint.')
  if (rows.some(item => !retained.has(investmentIdentity(item.row)))) blockers.push('Necessary source identities are omitted. Excluding them cannot establish complete coverage.')
  if (rows.some(item => item.valid && item.decision?.choice === 'skip' && item.canonicalId && !rows.some(other => other.row.id === item.canonicalId && other.valid && other.decision?.choice !== 'exclude'))) blockers.push('A skipped copy requires a retained canonical row decision.')
  if (batch.mode !== 'snapshot' && allEvidence.some(item => item.normalized.kind === 'lot' && (!item.normalized.fee || !item.normalized.basis || !item.normalized.amount || !item.row.original.date))) blockers.push('Lot acquisition, fees, or tax basis are unavailable. Remaining units and current value cannot fill the gaps.')
  const supplied = new Map(batch.baseline.rows.map(row => [investmentIdentity(row), row]))
  for (const item of preview) if (item.disposition !== 'duplicate') supplied.set(investmentIdentity(item.row), item.row)
  const sourceChecks = checks(batch, [...supplied.values()]), selectedChecks = checks(batch, [...retained.values()])
  if (!sourceChecks.length || sourceChecks.some(check => !check.passed)) blockers.push('Supplied position, lot, activity, or cash checks are incomplete or have a difference.')
  if (selectedChecks.some(check => !check.passed)) blockers.push('Retained comparison plus selected records fails the declared scope checks.')
  const key = investmentEvidence([batch, Object.entries(current.decisions).sort(([a], [b]) => a.localeCompare(b))])
  const receipt = current.receipt?.key === key && !blockers.length ? current.receipt : null
  if (current.receipt && !receipt) blockers.push('Previous completion is incompatible with current evidence. Reopen before further review.')
  const selected = [...retained.values()], groups = investmentMoneyGroups(batch, selected)
  return { rows, counts, blockers, reasons, sourceChecks, selectedChecks, selected, groups, receipt, key, ready: !blockers.length && !current.aside, aside: current.aside, newIdentities: rows.filter(row => row.valid && row.decision?.choice === 'include' && !batch.baseline.rows.some(existing => investmentIdentity(existing) === investmentIdentity(row.row))).length }
}
export function proposeInvestment(batch: InvestmentBatch, state: ImportReviewState, operation: InvestmentOperation): InvestmentProposal {
  return { batchId: batch.id, operation, token: investmentEvidence([batch, state.serial, investmentBatchReview(state, batch.id), operation]) }
}
export function changeInvestmentReview(state: ImportReviewState, batch: InvestmentBatch, proposal: InvestmentProposal, visible = true): ImportReviewState {
  const fail = (message: string) => ({ ...state, message }), current = investmentBatchReview(state, batch.id), operation = proposal.operation
  if (!visible) return fail('Show amounts and load the sample before changing its review.')
  if (!['row', 'suggestions', 'complete', 'aside', 'reopen'].includes(operation.type)) return fail('Unsupported review action. Nothing was applied.')
  if (operation.type === 'complete' && reviewInvestment(batch, state).receipt && proposal.batchId === batch.id && current.receipt?.token === proposal.token) return state
  if (proposal.batchId !== batch.id || proposal.token !== proposeInvestment(batch, state, operation).token) return fail('Evidence or decisions changed. Open a fresh preview; nothing was applied.')
  if ((current.aside || current.receipt) && operation.type !== 'reopen' && operation.type !== 'complete') return fail('Reopen this sample review before changing choices.')
  const next: InvestmentBatchReview = { ...current, decisions: { ...current.decisions }, receipt: null }, preview = previewInvestment(batch)
  let label: string = operation.type
  function decide(item: InvestmentPreviewRow, choice: InvestmentChoice) {
    next.decisions[item.row.id] = { choice, evidence: investmentEvidence(batch), reason: reason(item, choice), original: copy(item.row), matches: [...item.matches, ...preview.filter(other => other.row.id === item.canonicalId).map(other => other.row)].map(copy), previous: current.decisions[item.row.id]?.choice ?? null }
  }
  if (operation.type === 'row') {
    const item = preview.find(item => item.row.id === operation.rowId)
    if (!item) return fail('This source row is unavailable. Nothing was applied.')
    if (operation.choice === 'restore') { if (!current.decisions[item.row.id]) return state; delete next.decisions[item.row.id] }
    else { if (!permittedInvestmentChoices(item).includes(operation.choice)) return fail('The supplied evidence does not support this choice. Nothing was applied.'); decide(item, operation.choice) }
    label = `${item.row.id} · ${operation.choice === 'restore' ? 'Decision restored' : investmentChoices[operation.choice]}`
  } else if (operation.type === 'suggestions') {
    for (const item of preview) if (!current.decisions[item.row.id]) {
      if (item.disposition === 'new') decide(item, 'include')
      else if (item.disposition === 'present' || item.disposition === 'duplicate') decide(item, 'skip')
    }
    if (investmentEvidence(next.decisions) === investmentEvidence(current.decisions)) return state
    label = 'Applied eligible investment choices'
  } else if (operation.type === 'complete') {
    const review = reviewInvestment(batch, state)
    if (review.receipt) return state
    if (!review.ready) return fail('Completion is blocked by unresolved evidence. No receipt was created.')
    next.receipt = { key: review.key, token: proposal.token, revision: batch.revision, scope: batch.scope, counts: { ...review.counts }, reasons: [...review.reasons], groups: review.groups }
    label = 'Completed investment sample · No records saved'
  } else if (operation.type === 'aside') { next.aside = true; label = 'Set investment sample aside' }
  else { next.aside = false; label = 'Reopened investment sample' }
  return { ...state, investments: { ...state.investments, [batch.id]: next }, serial: state.serial + 1, history: [...state.history, { before: state.batches, investmentsBefore: state.investments, batch: batch.id, label }], message: label }
}
