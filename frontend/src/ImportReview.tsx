import { useContext, useEffect, useRef, useState } from 'react'
import { Check, RotateCcw, ShieldCheck } from 'lucide-react'
import { DisplayContext, ReportingAmount } from './display'
import { bankNames } from './data/banking'
import { batchReview, changeImportReview, distinctEvidence, permittedChoices, proposeImport, reviewImport } from './data/import-review'
import type { ImportOperation, ImportProposal, ImportReviewState } from './data/import-review'
import { previewImport } from './data/imports'
import type { ImportBatch, PreviewRow } from './data/imports'

export interface ReviewProps { batch: ImportBatch; state: ImportReviewState; onAction: (proposal: ImportProposal) => void }
const actionLabels = { include: 'Include candidate', skip: 'Skip as duplicate', exclude: 'Exclude from this sample review', restore: 'Restore row decision' } as const

export function RowReview({ batch, item, state, onAction }: ReviewProps & { item: PreviewRow }) {
  const { hidden } = useContext(DisplayContext), [pending, setPending] = useState<ImportProposal | null>(null)
  const current = batchReview(state, batch.id), row = reviewImport(batch, state).rows.find(row => row.row.id === item.row.id)!
  const proof = distinctEvidence(batch, item), locked = current.aside || Boolean(current.receipt)
  const focus = useRef<HTMLHeadingElement>(null), origin = useRef<HTMLButtonElement | null>(null)
  useEffect(() => { setPending(null) }, [hidden, state.serial, batch.id])
  useEffect(() => { if (pending) focus.current?.focus({ preventScroll: true }) }, [pending])
  function finish(apply: boolean) { if (apply && pending) onAction(pending); setPending(null); requestAnimationFrame(() => origin.current?.focus()) }
  return <section className="import-row-review" aria-label="Row review decision"><h3>Review decision</h3><strong role="status">{row.status}</strong>
    <p className="inspector-note">Expected source account: {bankNames[batch.account]} · Sample owner. Incoming identity must match; incompatible identities remain blocked. No alternate mapping or field editor is available.</p>
    {proof && <p className="import-proof"><ShieldCheck size={16} aria-hidden="true" />{proof}</p>}
    {row.valid && <p className="inspector-note">{row.decision?.reason}</p>}
    {locked ? <p className="inspector-note">Reopen this sample review from the batch summary to change decisions.</p> : <>
      <div className="import-review-actions">{[...permittedChoices(batch, item), ...(row.decision ? ['restore' as const] : [])].map(choice => <button key={choice} className={choice === 'include' || choice === 'skip' ? 'primary-button' : 'outlined-button'} disabled={hidden} onClick={event => { origin.current = event.currentTarget; setPending(proposeImport(batch, state, { type: 'row', rowId: item.row.id, choice })) }}>{actionLabels[choice]}</button>)}</div>
      {hidden && <p className="inspector-note">Show amounts to review a change. Undo and reset remain available in the batch summary.</p>}
      {!hidden && pending?.operation.type === 'row' && <div className="import-confirm" role="region" aria-label="Confirm row decision"><h4 ref={focus} tabIndex={-1}>{actionLabels[pending.operation.choice]}?</h4><p>{pending.operation.choice === 'exclude' ? 'Reason: set aside for further source review. Required evidence and financial blockers remain.' : pending.operation.choice === 'restore' ? 'Return this row to Needs decision. The original evidence remains unchanged.' : pending.operation.choice === 'skip' ? 'Add no new movement for this occurrence. The matching evidence or canonical row in this inspector must account for this identity.' : 'Treat this as a distinct proposed record in this sample review.'}</p><div className="import-confirm-amount"><span>Source {item.normalized.direction ?? 'direction unavailable'}</span><ReportingAmount value={item.normalized.amount} /></div><div className="import-review-actions"><button className="primary-button" onClick={() => finish(true)}>Confirm row choice</button><button className="outlined-button" onClick={() => finish(false)}>Cancel row choice</button></div></div>}
    </>}
  </section>
}

function ReviewNumbers({ review, preview = false }: { review: ReturnType<typeof reviewImport>; preview?: boolean }) {
  const { currency } = useContext(DisplayContext)
  return <><dl className="import-review-counts">{Object.entries(review.counts).map(([label, count]) => <div key={label}><dt>{label === 'present' ? 'Already present' : label === 'unresolved' ? 'Needs decision' : label}</dt><dd>{count}</dd></div>)}</dl>
    <div className="import-review-movements"><section aria-label={preview ? 'Preview proposed incremental movements' : 'Proposed incremental movements'}><h3>Proposed unique additions</h3><p>Primary amounts in {currency}. Pending movements stay separate.</p>{review.proposed.groups.length ? review.proposed.groups.map(group => <div className="import-native-group" key={`${group.currency}-${group.status}`}><strong>{group.currency} source · {group.status} · {group.count} {group.count === 1 ? 'row' : 'rows'}</strong><dl><div><dt>Credits</dt><dd><ReportingAmount value={group.credits} /></dd></div><div><dt>Debits</dt><dd><ReportingAmount value={group.debits} /></dd></div><div><dt>Net movement</dt><dd><ReportingAmount value={group.net} /></dd></div></dl></div>) : <p>No proposed additions.</p>}</section>
      <section aria-label={preview ? 'Preview combined record reconciliation' : 'Combined record reconciliation'}><h3>Baseline + unique additions</h3><p>Same source account, currency, and statement period. Existing identities count once.</p><dl><div><dt>Calculated closing</dt><dd><ReportingAmount value={review.computed} /></dd></div><div><dt>Closing − calculated</dt><dd><ReportingAmount value={review.difference} /></dd></div></dl></section></div></>
}

export default function ImportReview({ batch, state, onAction, onUndo, onReset }: ReviewProps & { onUndo: () => void; onReset: () => void }) {
  const { hidden } = useContext(DisplayContext), [pending, setPending] = useState<ImportProposal | null>(null), [reset, setReset] = useState(false)
  const review = reviewImport(batch, state), current = batchReview(state, batch.id)
  const focus = useRef<HTMLHeadingElement>(null), origin = useRef<HTMLButtonElement | null>(null)
  useEffect(() => { setPending(null); setReset(false) }, [hidden, state.serial, batch.id])
  useEffect(() => { if (pending || reset) focus.current?.focus({ preventScroll: true }) }, [pending, reset])
  const preview = pending ? reviewImport(batch, changeImportReview(state, batch, pending)) : review
  const locked = current.aside || Boolean(current.receipt)
  const eligible = review.rows.filter(row => !row.decision && ['new', 'present', 'duplicate'].includes(row.disposition)).length
  function begin(operation: ImportOperation, button: HTMLButtonElement) { origin.current = button; setReset(false); setPending(proposeImport(batch, state, operation)) }
  function finish(apply: boolean) { if (apply && pending) onAction(pending); setPending(null); setReset(false); requestAnimationFrame(() => (origin.current?.isConnected ? origin.current : document.getElementById('import-review-title'))?.focus()) }
  return <section className="panel import-review" aria-labelledby="import-review-title">
    <div className="connection-section-heading"><div><span className="eyebrow">Your review · {batch.id} / {batch.revision}</span><h2 id="import-review-title" tabIndex={-1}>{review.receipt ? 'Sample review completed.' : review.aside ? 'This sample is set aside.' : review.ready ? 'Ready for a final look.' : 'Decide what belongs.'}</h2><p>{review.receipt ? 'Sample only — no records saved' : 'Choices stay in this session. Your financial workspace stays unchanged.'}</p></div>{review.receipt ? <Check size={25} aria-hidden="true" /> : <ShieldCheck size={25} aria-hidden="true" />}</div>
    <ReviewNumbers review={review} />
    {review.blockers.length > 0 && <details className="import-review-blockers"><summary>{review.blockers.length} completion checks need attention</summary><ul className="import-reasons">{review.blockers.map(reason => <li key={reason}>{reason}</li>)}</ul></details>}
    <div className="import-review-toolbar"><div className="import-review-actions">{locked ? <button className="primary-button" disabled={hidden} onClick={event => begin({ type: 'reopen' }, event.currentTarget)}>Reopen sample review</button> : <><button className="outlined-button" disabled={hidden || !eligible} onClick={event => begin({ type: 'suggestions' }, event.currentTarget)}>Review suggested choices{eligible > 0 ? ` (${eligible})` : ''}</button><button className="primary-button" disabled={hidden || !review.ready} onClick={event => begin({ type: 'complete' }, event.currentTarget)}>Complete sample review</button><button className="text-button" disabled={hidden} onClick={event => begin({ type: 'aside' }, event.currentTarget)}>Set sample aside</button></>}
      <button className="text-button" disabled={!state.history.length} onClick={onUndo}><RotateCcw size={15} aria-hidden="true" />Undo review change</button><button className="text-button" onClick={event => { origin.current = event.currentTarget; setPending(null); setReset(true) }}>Reset sample import reviews</button></div>{hidden && <p>Show amounts to change decisions or complete this review.</p>}<p role="status">{state.message}</p></div>
    {!hidden && pending && <section className="import-confirm import-batch-confirm" aria-label="Review change preview"><h3 ref={focus} tabIndex={-1}>{pending.operation.type === 'complete' ? 'Complete this sample review?' : pending.operation.type === 'suggestions' ? 'Review suggested choices' : pending.operation.type === 'reopen' ? 'Reopen this review?' : 'Set this sample aside?'}</h3><p>{pending.operation.type === 'suggestions' ? 'Include valid new candidates and skip exact matches/copies that have no prior choice. Possible overlaps still need individual inspection. Existing choices stay as they are.' : pending.operation.type === 'complete' ? 'Record an in-memory receipt for this revision and these decisions. Sample only — no records saved.' : pending.operation.type === 'reopen' ? 'Remove the current completion receipt or set-aside status and retain your row decisions for further review.' : 'Keep your choices and pause this review. Exclusions and unresolved source evidence still block completion.'}</p><ReviewNumbers review={preview} preview /><p>{batch.coverageNote}</p><p>Source arithmetic: {previewImportStatus(batch)}. Proposed coverage: {preview.blockers.length ? 'Checks remain unresolved' : 'Complete for the supplied period'}.</p><details><summary>Decision reasons · {preview.reasons.length} rows</summary><ul className="import-reasons">{preview.reasons.map(reason => <li key={reason}>{reason}</li>)}</ul></details><div className="import-review-actions"><button className="primary-button" onClick={() => finish(true)}>{pending.operation.type === 'complete' ? 'Confirm sample completion' : 'Confirm review change'}</button><button className="outlined-button" onClick={() => finish(false)}>Cancel review change</button></div></section>}
    {reset && <div className="import-confirm import-batch-confirm" role="region" aria-label="Reset import reviews"><h3 ref={focus} tabIndex={-1}>Reset all sample import reviews?</h3><p>Clear decisions, receipts, and this history across all bank and investment samples. Connection simulations and other workspace reviews keep their own state.</p><div className="import-review-actions"><button className="primary-button" onClick={() => { onReset(); finish(false) }}>Confirm import reset</button><button className="outlined-button" onClick={() => finish(false)}>Cancel import reset</button></div></div>}
    {review.receipt && !hidden && <details className="import-receipt"><summary>Review receipt · {batch.id} / {review.receipt.revision}</summary><p>Sample only — no records saved. {review.counts.included} included, {review.counts.present} already present, {review.counts.excluded} excluded, {review.counts.unresolved} unresolved. Both native reconciliation checks passed. Coverage: {batch.coverageNote}</p><ul className="import-reasons">{review.receipt.reasons.map(reason => <li key={reason}>{reason}</li>)}</ul></details>}
    {state.history.length > 0 && <details className="import-review-history"><summary>Import review history · {state.history.length} changes</summary><ol>{state.history.map((entry, index) => <li key={index}><span>{entry.batch}</span> {entry.label}</li>)}</ol><p>Session-only review history. Reload clears it.</p></details>}
  </section>
}

function previewImportStatus(batch: ImportBatch) { return previewImport(batch).reconciliation.status === 'matches' ? 'Supplied balances match' : 'Unavailable or unexplained difference' }
