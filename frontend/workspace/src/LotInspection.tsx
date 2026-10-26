import { useEffect, useRef, useState } from 'react'
import { ArrowLeft, ArrowRight, History, Layers3, RefreshCw } from 'lucide-react'
import type { AuthController } from './auth'
import { exactValue } from './investments'
import type { Page, Position } from './investments'
import { lotPage, observationHistory, observationPage } from './lot-evidence'
import type { Lot, LotHistory, LotObservation } from './lot-evidence'
import ReceiptInspection from './ReceiptInspection'
import { receiptContext, receiptPage } from './receipt-evidence'
import type { ReceiptContext, SavedReceipt } from './receipt-evidence'

type View = { kind: 'receipt'; lot: Lot; context: ReceiptContext; page: Page<SavedReceipt> } | { kind: 'lots'; page: Page<Lot>; after: string | null }
  | { kind: 'observations'; lot: Lot; page: Page<LotObservation>; after: string | null }
  | { kind: 'history'; lot: Lot; root: Pick<LotObservation, 'id' | 'scope' | 'revision'>; page: LotHistory; before: number | null }
const coverage = { snapshot: 'Snapshot evidence only', partial_activity: 'Partial activity reported', complete_activity: 'Source claims complete activity', unknown: 'Coverage unknown' }
const scope = { lot_acquisition: 'Acquisition observation', lot_remaining: 'Remaining-lot observation' }
const reason = { source_correction: 'Source correction', cancellation: 'Cancellation', reinstatement: 'Reinstatement' }
const roles = ['quantity', 'unit_price', 'acquisition_cost', 'discount_amount', 'reported_tax_basis', 'fee', 'withholding'] as const
const labels = { quantity: 'Quantity', unit_price: 'Supplied unit price', acquisition_cost: 'Supplied purchase cost', discount_amount: 'Supplied monetary discount', reported_tax_basis: 'Reported tax basis', fee: 'Supplied fee', withholding: 'Supplied withholding' }

function Observation({ item, masked, onHistory, onReceipt, disabled }: { item: LotObservation; masked: boolean; onHistory?: () => void; onReceipt: () => void; disabled: boolean }) {
  return <article className="wi-evidence">
    <div className="wi-line"><h4>{scope[item.scope]}</h4><span className="ws-pill">{item.status === 'cancelled' ? 'Cancelled evidence' : 'Active evidence'} · Revision {item.revision}</span></div>
    <p className="ws-hint">{item.is_current ? 'Latest retained revision' : 'Earlier retained revision'} · {item.correction_reason ? reason[item.correction_reason] : 'Original evidence'} · {item.account_state === 'archived' ? 'Archived account' : 'Active account'}</p>
    <dl className="wi-meta"><div><dt>Observed as of</dt><dd>{item.as_of_date ?? 'Not supplied'}</dd></div><div><dt>Acquisition date</dt><dd>{item.acquisition_date ?? 'Not supplied'}</dd></div><div><dt>Booking date</dt><dd>{item.booking_date ?? 'Not supplied'}</dd></div></dl>
    {item.status === 'cancelled' ? <p className="ws-notice">This revision withdraws the observation. It has no financial components; earlier evidence remains in revision history. No zero balance or reversing transaction is invented.</p>
      : <><dl className="wi-values">{roles.map(role => { const value = item.components.find(value => value.role === role); return <div key={role}><dt>{role === 'quantity' ? item.scope === 'lot_acquisition' ? 'Original acquisition quantity' : 'Reported remaining quantity' : labels[role]}</dt><dd>{masked ? '••••' : value ? exactValue(value, false) : 'Not supplied by this observation'}</dd></div> })}</dl><p className="ws-hint">{item.scope === 'lot_acquisition' ? 'Original acquired units do not establish remaining units or subsequent disposals.' : 'Remaining units do not reconstruct the original purchase or disposal history. Zero units do not identify a sale.'} Purchase cost, monetary discount and reported tax basis are independent source values.</p></>}
    <details><summary>Source and coverage · {coverage[item.coverage]}</summary><dl className="wi-meta"><div><dt>Reported period</dt><dd>{item.period_start ? `${item.period_start} to ${item.period_end}` : 'Not supplied'}</dd></div><div><dt>Observation</dt><dd>{item.id}</dd></div><div><dt>Source</dt><dd>{item.source_id}</dd></div><div><dt>Source observation</dt><dd>{item.observation_id}</dd></div><div><dt>Source batch</dt><dd>{item.batch_id}</dd></div><div><dt>Source row</dt><dd>{item.source_row_id}</dd></div><div><dt>Source review revision</dt><dd>{item.source_review_revision}</dd></div><div><dt>Cash date basis</dt><dd>{item.cash_date_basis ?? 'Not supplied'}</dd></div></dl><p className="ws-hint">Coverage describes this source and supplied period. It does not establish a reconciled completion, lifetime history or tax calculation. Latest revision does not mean fresh or complete.</p><button className="ws-text" disabled={disabled} onClick={onReceipt}>Inspect batch completion for observation {item.id}, revision {item.revision}</button></details>
    {onHistory && <button className="ws-text" disabled={disabled} onClick={onHistory}>Inspect revisions for observation {item.id}<History size={15} aria-hidden="true" /></button>}
  </article>
}

export default function LotInspection({ auth, position, initial, masked, busy, onBack }: { auth: AuthController; position: Position; initial: Page<Lot>; masked: boolean; busy: boolean; onBack: () => void }) {
  const [view, setView] = useState<View | undefined>({ kind: 'lots', page: initial, after: null })
  const [loading, setLoading] = useState(false), [failed, setFailed] = useState(false)
  const mounted = useRef(true), generation = useRef(0), heading = useRef<HTMLHeadingElement>(null)
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; generation.current++ } }, [])
  useEffect(() => { heading.current?.focus() }, [view, loading, failed])
  const disabled = busy || loading
  const work = async (read: () => Promise<View | undefined>) => {
    const current = ++generation.current
    setView(undefined); setFailed(false); setLoading(true)
    try { const next = await read(); if (mounted.current && current === generation.current) setView(next) }
    catch { if (mounted.current && current === generation.current) setFailed(true) }
    finally { if (mounted.current && current === generation.current) setLoading(false) }
  }
  const lots = (after: string | null = null) => work(async () => {
    const result = await auth.finance('/lots/query', { position_id: position.id, limit: 25, after }, value => lotPage(value, position, after))
    return result && { kind: 'lots', page: result, after }
  })
  const observations = (lot: Lot, after: string | null = null) => work(async () => {
    const result = await auth.finance('/lots/observations/query', { lot_id: lot.id, limit: 25, after }, value => observationPage(value, lot, after))
    return result && { kind: 'observations', lot, page: result, after }
  })
  const history = (lot: Lot, root: Pick<LotObservation, 'id' | 'scope' | 'revision'>, before: number | null = null) => work(async () => {
    const result = await auth.finance('/lots/observations/history', { id: root.id, limit: 25, before }, value => observationHistory(value, lot, root, before))
    return result && { kind: 'history', lot, root, page: result, before }
  })
  const completion = (lot: Lot, item: LotObservation) => work(async () => {
    const context = receiptContext('lot', item)
    const result = await auth.finance('/receipts/query', { batch_id: context.batch_id, limit: 25, after: null }, value => receiptPage(value, context))
    return result && { kind: 'receipt', lot, context, page: result }
  })
  if (view?.kind === 'receipt') return <ReceiptInspection navigation={{ mode: 'full' }} auth={auth} masked={masked} context={view.context} initial={view.page} busy={busy} onBack={() => void observations(view.lot)} />
  return <section className="wi-lots" aria-labelledby="lot-heading">
    <button className="ws-text" disabled={disabled} onClick={onBack}><ArrowLeft size={16} aria-hidden="true" />Back to positions</button>
    <div className="wi-detail-title"><span className="ws-eyebrow">Supplied acquisition evidence</span><h3 id="lot-heading" tabIndex={-1} ref={heading}>Lot evidence</h3><p>Position {position.id}</p></div>
    <p className="ws-notice">Lot identities and observations are source evidence. They are not summed or automatically selected. No remaining balance, disposal allocation, calculated cost basis, tax or investment return is inferred.</p>
    {loading && <p role="status" className="wi-empty">Checking saved lot evidence…</p>}
    {failed && <div role="alert" className="ws-notice"><strong>Lot evidence could not be verified.</strong><p>Earlier values have been cleared. No automatic retry is performed.</p><button className="ws-text" disabled={disabled} onClick={() => void lots()}>Reload lot identities</button></div>}
    {view?.kind === 'lots' && <><div className="wi-line"><h4>Saved lot identities</h4><button className="ws-text" disabled={disabled} onClick={() => void lots(view.after)}><RefreshCw size={14} aria-hidden="true" />Refresh lots</button></div><p className="ws-hint">Identity order is not acquisition-date order. A lot identity contains no quantity.</p>
      {!view.page.items.length && <p className="wi-empty">No lot identities on this page. Missing evidence does not mean zero holdings.</p>}
      {view.page.items.map(lot => <article className="wi-evidence" key={lot.id}><div className="wi-line"><h4>Lot {lot.id}</h4><span className="ws-pill">{lot.account_state === 'archived' ? 'Archived account' : 'Active account'}</span></div><button className="ws-text" disabled={disabled} onClick={() => void observations(lot)}>Inspect observations for lot {lot.id}<Layers3 size={15} aria-hidden="true" /></button></article>)}
      <div className="wi-line"><button className="ws-text" disabled={disabled || view.after === null} onClick={() => void lots()}>First lots</button><button className="ws-text" disabled={disabled || !view.page.next_after} onClick={() => void lots(view.page.next_after)}>Next lots<ArrowRight size={14} aria-hidden="true" /></button></div></>}
    {view?.kind === 'observations' && <><button className="ws-text" disabled={disabled} onClick={() => void lots()}>Back to lot identities</button><h4>Observations for lot {view.lot.id}</h4><p className="ws-hint">Each row is the latest revision of one independent observation, including cancellations. Earlier pages are replaced, not accumulated. Acquisition and remaining-lot observations may overlap.</p>
      {!view.page.items.length && <p className="wi-empty">No observations on this page. Acquisition and remaining quantities are unknown.</p>}
      {view.page.items.map(item => <Observation key={item.id} item={item} masked={masked} disabled={disabled} onReceipt={() => void completion(view.lot, item)} onHistory={() => void history(view.lot, { id: item.id, scope: item.scope, revision: item.revision })} />)}
      <div className="wi-line"><button className="ws-text" disabled={disabled || view.after === null} onClick={() => void observations(view.lot)}>First observations</button><button className="ws-text" disabled={disabled || !view.page.next_after} onClick={() => void observations(view.lot, view.page.next_after)}>Next observations</button></div></>}
    {view?.kind === 'history' && <><button className="ws-text" disabled={disabled} onClick={() => void observations(view.lot)}>Back to current observations</button><h4>Observation revision history</h4><p className="ws-hint">Newest revisions first. Earlier active values remain historical evidence after correction or cancellation. Reload the first page to discover newer revisions.</p>
      {!view.page.items.length && <p className="wi-empty">No revisions on this page. This does not establish complete source history.</p>}
      {view.page.items.map(item => <Observation key={item.revision} item={item} masked={masked} disabled={disabled} onReceipt={() => void completion(view.lot, item)} />)}
      <div className="wi-line"><button className="ws-text" disabled={disabled || view.before === null} onClick={() => void history(view.lot, view.root)}>Latest revisions</button><button className="ws-text" disabled={disabled || !view.page.next_before} onClick={() => void history(view.lot, view.root, view.page.next_before)}>Earlier revisions</button></div></>}
  </section>
}
