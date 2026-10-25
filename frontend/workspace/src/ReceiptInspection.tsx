import { useEffect, useRef, useState } from 'react'
import { ArrowLeft, ArrowRight, FileCheck2, RefreshCw } from 'lucide-react'
import type { AuthController } from './auth'
import type { Page } from './investments'
import { completedRows, emptyReceiptProgress, receiptPage } from './receipt-evidence'
import type { CompletedPage, ReceiptContext, ReceiptProgress, SavedReceipt } from './receipt-evidence'

type View = { kind: 'receipts'; page: Page<SavedReceipt>; after: string | null } | { kind: 'rows'; receipt: SavedReceipt; page: CompletedPage; after: string | null; preceding: ReceiptProgress }
const coverage = { snapshot: 'Snapshot evidence only', partial_activity: 'Partial activity', complete_activity: 'Complete activity for the saved scope', unknown: 'Coverage unknown' }
const outcome = { recorded: 'Recorded', linked: 'Linked existing evidence', corrected: 'Corrected', excluded: 'Excluded' }
function Metadata({ receipt }: { receipt: SavedReceipt }) {
  return <><div className="wi-line"><h4>Saved completion</h4><span className="ws-pill">{receipt.mode === 'limited' ? 'Limited coverage' : 'Reconciled at completion'}</span></div><dl className="wi-meta"><div><dt>Receipt</dt><dd>{receipt.id}</dd></div><div><dt>Completed at</dt><dd>{receipt.created_at}</dd></div><div><dt>Batch revision</dt><dd>{receipt.batch_revision}</dd></div><div><dt>Coverage</dt><dd>{coverage[receipt.coverage]}</dd></div><div><dt>Source rows</dt><dd>{receipt.row_count}</dd></div><div><dt>Saved selections</dt><dd>{receipt.selection_count}</dd></div><div><dt>Comparison scopes</dt><dd>{receipt.scope_count}</dd></div></dl><p className="ws-hint">{receipt.mode === 'limited' ? 'No reconciliation comparison was retained for this completion.' : 'Reconciliation applies only to the frozen scopes at this completion. Equations and compared inputs are not inspected here.'} These counts describe the whole batch and do not establish current holdings or complete account history.</p></>
}
export default function ReceiptInspection({ auth, context, initial, busy, onBack }: { auth: AuthController; context: ReceiptContext; initial: Page<SavedReceipt>; busy: boolean; onBack: () => void }) {
  const [view, setView] = useState<View | undefined>({ kind: 'receipts', page: initial, after: null })
  const [loading, setLoading] = useState(false), [failed, setFailed] = useState(false)
  const mounted = useRef(true), generation = useRef(0), heading = useRef<HTMLHeadingElement>(null)
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; generation.current++ } }, [])
  useEffect(() => { heading.current?.focus() }, [view, loading, failed])
  const disabled = busy || loading
  const work = async (read: () => Promise<View | undefined>) => {
    const current = ++generation.current; setView(undefined); setFailed(false); setLoading(true)
    try { const next = await read(); if (mounted.current && current === generation.current) setView(next) }
    catch { if (mounted.current && current === generation.current) setFailed(true) }
    finally { if (mounted.current && current === generation.current) setLoading(false) }
  }
  const receipts = (after: string | null = null) => work(async () => {
    const result = await auth.finance('/receipts/query', { batch_id: context.batch_id, limit: 25, after }, value => receiptPage(value, context, after))
    return result && { kind: 'receipts', page: result, after }
  })
  const rows = (receipt: SavedReceipt, after: string | null = null, preceding: ReceiptProgress = emptyReceiptProgress) => work(async () => {
    const result = await auth.finance('/receipts/rows/query', { receipt_id: receipt.id, limit: 25, after }, value => completedRows(value, receipt, context, after, preceding))
    return result && { kind: 'rows', receipt, page: result, after, preceding }
  })
  return <section className="wi-receipts" aria-labelledby="receipt-heading">
    <button className="ws-text" disabled={disabled} onClick={onBack}><ArrowLeft size={16} aria-hidden="true" />Back to {context.kind === 'event' ? 'account activity' : 'lot observations'}</button>
    <div className="wi-detail-title"><span className="ws-eyebrow">Historical completion evidence</span><h3 id="receipt-heading" tabIndex={-1} ref={heading}>Batch completion</h3><p>Batch {context.batch_id}<br />Opened from {context.kind === 'event' ? 'event' : 'lot observation'} {context.id} · revision {context.revision}</p></div>
    <p className="ws-notice">Receipts describe a completed historical operation for the whole batch. They can include other positions and cash evidence. Later corrections or changed selections do not rewrite a receipt, and it does not establish current balances, tax basis or lifetime history.</p>
    {loading && <p role="status" className="wi-empty">Checking saved completion evidence…</p>}
    {failed && <div role="alert" className="ws-notice"><strong>Completion evidence could not be verified.</strong><p>Earlier details have been cleared. No automatic retry is performed.</p><button className="ws-text" disabled={disabled} onClick={() => void receipts()}>Reload batch receipts</button></div>}
    {view?.kind === 'receipts' && <><div className="wi-line"><h4>Receipts for this batch</h4><button className="ws-text" disabled={disabled} onClick={() => void receipts(view.after)}><RefreshCw size={14} aria-hidden="true" />Refresh receipts</button></div><p className="ws-hint">Pages use stable identity order, not completion-time order. Source coverage claims and saved completion effects are separate evidence.</p>
      {!view.page.items.length && <p className="wi-empty">No completion receipt on this page. This does not establish zero activity, invalid evidence or a complete import history.</p>}
      {view.page.items.map(receipt => <article className="wi-evidence" key={receipt.id}><Metadata receipt={receipt} /><button className="ws-text" disabled={disabled} onClick={() => void rows(receipt)}>Inspect row effects for receipt {receipt.id}<FileCheck2 size={15} aria-hidden="true" /></button></article>)}
      <div className="wi-line"><button className="ws-text" disabled={disabled || view.after === null} onClick={() => void receipts()}>First receipt page</button><button className="ws-text" disabled={disabled || !view.page.next_after} onClick={() => void receipts(view.page.next_after)}>Next receipt page<ArrowRight size={14} aria-hidden="true" /></button></div></>}
    {view?.kind === 'rows' && <><button className="ws-text" disabled={disabled} onClick={() => void receipts()}>Back to batch receipts</button><article className="wi-evidence"><Metadata receipt={view.receipt} /></article><div className="wi-line"><h4>Historical row effects</h4><button className="ws-text" disabled={disabled} onClick={() => void rows(view.receipt, view.after, view.preceding)}><RefreshCw size={14} aria-hidden="true" />Refresh row effects</button></div><p className="ws-hint">All effects on this page remain visible. An exact originating row is labeled only when source row, review revision, target identity and saved record revision agree. An absent row on one page is not a missing or excluded completion.</p>
      {view.page.items.map(row => <article className="wi-evidence" key={row.id}><div className="wi-line"><h4>{outcome[row.outcome]}</h4><span className="ws-pill">{row.id === context.source_row_id ? 'Originating evidence revision' : 'Another source row in this batch'}</span></div><dl className="wi-meta"><div><dt>Source row</dt><dd>{row.id}</dd></div><div><dt>Review revision</dt><dd>{row.review_revision}</dd></div><div><dt>Operation</dt><dd>{row.operation}</dd></div>{row.record_revision !== null && <><div><dt>Saved target</dt><dd>{row.event_id ? 'Event' : row.lot_observation_id ? 'Lot observation' : 'Snapshot'} {row.event_id ?? row.lot_observation_id ?? row.snapshot_id}</dd></div><div><dt>Saved revision</dt><dd>{row.record_revision}</dd></div></>}{row.provider_identity_id && <div><dt>Identity link</dt><dd>{row.provider_identity_id}</dd></div>}{row.selection_id && <><div><dt>Selection</dt><dd>{row.selection_id}</dd></div><div><dt>Selection revision</dt><dd>{row.selection_revision}</dd></div></>}</dl><p className="ws-hint">{row.outcome === 'excluded' ? 'No financial target was created by this exclusion.' : row.outcome === 'linked' ? 'The source occurrence linked to existing evidence. It is not an additional movement.' : row.outcome === 'corrected' ? 'This records the correction made at completion, not a current selection or a new independent movement.' : 'This records the saved target revision at completion. Its present state may differ.'}</p></article>)}
      <div className="wi-line"><button className="ws-text" disabled={disabled || view.after === null} onClick={() => void rows(view.receipt)}>First row page</button><button className="ws-text" disabled={disabled || !view.page.next_after} onClick={() => void rows(view.receipt, view.page.next_after, view.page.progress)}>Next row page<ArrowRight size={14} aria-hidden="true" /></button></div></>}
  </section>
}