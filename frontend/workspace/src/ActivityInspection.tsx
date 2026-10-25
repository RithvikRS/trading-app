import { useEffect, useRef, useState } from 'react'
import { ArrowLeft, ArrowRight, History, RefreshCw, ScanSearch } from 'lucide-react'
import type { AuthController } from './auth'
import { coverageLabels, exactValue } from './investments'
import type { Page, Position, SourceObservation } from './investments'
import { activityCoveragePage, activityHistory, activityPage, eventIdentity, eventRoles } from './activity-evidence'
import type { ActivityHistory, EventEvidence, EventIdentity } from './activity-evidence'
import ReceiptInspection from './ReceiptInspection'
import { receiptContext, receiptPage } from './receipt-evidence'
import type { ReceiptContext, SavedReceipt } from './receipt-evidence'

type SourceContext = { source_id: string; event_id: string; revision: number }
type View = { kind: 'receipt'; context: ReceiptContext; page: Page<SavedReceipt> } | { kind: 'activity'; page: Page<EventEvidence>; after: string | null }
  | { kind: 'history'; root: EventIdentity; page: ActivityHistory; before: number | null }
  | { kind: 'coverage'; source: SourceContext; page: Page<SourceObservation>; after: string | null }
const kinds = { buy: 'Purchase', sell: 'Sale', subscription: 'Fund subscription', redemption: 'Fund redemption', dividend: 'Dividend', fee: 'Fee', withholding: 'Withholding', cash_movement: 'Cash movement' }
const reasons = { source_correction: 'Source correction', posting_update: 'Posting update', cancellation: 'Cancellation', reinstatement: 'Reinstatement' }
const roles = { quantity: 'Quantity movement', net_cash: 'Net cash movement', gross_cash: 'Supplied gross cash', unit_price: 'Supplied unit price', fee: 'Supplied fee', withholding: 'Supplied withholding' }

function Activity({ item, openedPosition, masked, disabled, onHistory, onCoverage, onReceipt }: { item: EventEvidence; openedPosition: string; masked: boolean; disabled: boolean; onHistory?: () => void; onCoverage: () => void; onReceipt: () => void }) {
  return <article className="wi-evidence">
    <div className="wi-line"><h4>{kinds[item.kind]}</h4><span className="ws-pill">{item.posting_state === 'posted' ? 'Posted' : 'Pending'} · {item.status === 'active' ? 'Active evidence' : 'Cancelled evidence'}</span></div>
    <p className="ws-hint">{item.is_current ? 'Latest retained revision' : 'Earlier retained revision'} {item.revision} · {item.correction_reason ? reasons[item.correction_reason] : 'Original evidence'} · {item.account_state === 'archived' ? 'Archived account' : 'Active account'}</p>
    <p className="wi-scope">{item.position_id === null ? 'Account-level cash or charge' : item.position_id === openedPosition ? 'Position opened from holdings' : 'Another position in this account'}{item.position_id && <><br />Position {item.position_id}<br />Instrument {item.instrument_id}</>}</p>
    <dl className="wi-meta"><div><dt>Trade date</dt><dd>{item.trade_date ?? 'Not supplied'}</dd></div><div><dt>Settlement date</dt><dd>{item.settlement_date ?? 'Not supplied'}</dd></div><div><dt>Booking date</dt><dd>{item.booking_date ?? 'Not supplied'}</dd></div><div><dt>Value date</dt><dd>{item.value_date ?? 'Not supplied'}</dd></div><div><dt>Cash date basis</dt><dd>{item.cash_date_basis ?? 'Not supplied'}</dd></div></dl>
    {item.status === 'cancelled' ? <p className="ws-notice">This revision withdraws the event evidence. It contains no financial components and creates no synthetic reversal or zero movement. Earlier values remain in revision history.</p>
      : <><dl className="wi-values">{eventRoles[item.kind].map(role => { const value = item.components.find(value => value.role === role); return <div key={role}><dt>{roles[role]}</dt><dd>{masked ? '••••' : value ? exactValue(value, false) : 'Not supplied by this revision'}</dd></div> })}</dl><p className="ws-hint">{item.posting_state === 'pending' ? 'Pending evidence is not a posted movement.' : 'Posted evidence remains limited to its supplied source and period.'} Components retain their source signs and native currencies; no balance, gain or cash-flow total is calculated.</p></>}
    <details><summary>Source and coverage · {coverageLabels[item.coverage]}</summary><dl className="wi-meta"><div><dt>Event</dt><dd>{item.id}</dd></div><div><dt>Reported period</dt><dd>{item.period_start ? `${item.period_start} to ${item.period_end}` : 'Not supplied'}</dd></div><div><dt>Source</dt><dd>{item.source_id}</dd></div><div><dt>Source observation</dt><dd>{item.observation_id}</dd></div><div><dt>Source batch</dt><dd>{item.batch_id}</dd></div><div><dt>Source row</dt><dd>{item.source_row_id}</dd></div><div><dt>Source review revision</dt><dd>{item.source_review_revision}</dd></div></dl><p className="ws-hint">These fields belong to this revision. A later correction can supply a different source, period or dates. Coverage does not establish reconciled completion, lifetime history or tax basis.</p><button className="ws-text" disabled={disabled} onClick={onReceipt}>Inspect batch completion for event {item.id}, revision {item.revision}</button></details>
    <div className="wi-toolbar">{onHistory && <button className="ws-text" disabled={disabled} onClick={onHistory}>Inspect revisions for event {item.id}<History size={15} aria-hidden="true" /></button>}<button className="ws-text" disabled={disabled} onClick={onCoverage}>Inspect source coverage for event {item.id}, revision {item.revision}<ScanSearch size={15} aria-hidden="true" /></button></div>
  </article>
}

export default function ActivityInspection({ auth, position, name, initial, masked, busy, onBack }: { auth: AuthController; position: Position; name: string; initial: Page<EventEvidence>; masked: boolean; busy: boolean; onBack: () => void }) {
  const [view, setView] = useState<View | undefined>({ kind: 'activity', page: initial, after: null })
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
  const activity = (after: string | null = null) => work(async () => {
    const result = await auth.finance('/events/query', { account_id: position.account_id, limit: 25, after }, value => activityPage(value, position, after))
    return result && { kind: 'activity', page: result, after }
  })
  const history = (root: EventIdentity, before: number | null = null) => work(async () => {
    const result = await auth.finance('/events/history', { id: root.id, limit: 25, before }, value => activityHistory(value, root, before))
    return result && { kind: 'history', root, page: result, before }
  })
  const coverage = (source: SourceContext, after: string | null = null) => work(async () => {
    const result = await auth.finance('/imports/observations/query', { source_id: source.source_id, limit: 25, after }, value => activityCoveragePage(value, source.source_id, after))
    return result && { kind: 'coverage', source, page: result, after }
  })
  const completion = (event: EventEvidence) => work(async () => {
    const context = receiptContext('event', event)
    const result = await auth.finance('/receipts/query', { batch_id: context.batch_id, limit: 25, after: null }, value => receiptPage(value, context))
    return result && { kind: 'receipt', context, page: result }
  })
  const item = (event: EventEvidence, historical = false) => <Activity key={`${event.id}-${event.revision}`} item={event} openedPosition={position.id} masked={masked} disabled={disabled} onReceipt={() => void completion(event)} onHistory={historical ? undefined : () => void history(eventIdentity(event))} onCoverage={() => void coverage({ source_id: event.source_id, event_id: event.id, revision: event.revision })} />
  if (view?.kind === 'receipt') return <ReceiptInspection auth={auth} masked={masked} context={view.context} initial={view.page} busy={busy} onBack={() => void activity()} />
  return <section className="wi-activity" aria-labelledby="activity-heading">
    <button className="ws-text" disabled={disabled} onClick={onBack}><ArrowLeft size={16} aria-hidden="true" />Back to positions</button>
    <div className="wi-detail-title"><span className="ws-eyebrow">Saved events and their sources</span><h3 id="activity-heading" tabIndex={-1} ref={heading}>Account activity</h3><p>Opened from {name}<br />Account {position.account_id}</p></div>
    <p className="ws-notice">Showing all saved events in this account, including other positions and account-level cash. Pages are not filtered to the position opened from holdings. No account balance, investment return, tax result or complete-history claim is derived.</p>
    {loading && <p role="status" className="wi-empty">Checking saved account activity…</p>}
    {failed && <div role="alert" className="ws-notice"><strong>Account activity could not be verified.</strong><p>Earlier values have been cleared. No automatic retry is performed.</p><button className="ws-text" disabled={disabled} onClick={() => void activity()}>Reload account activity</button></div>}
    {view?.kind === 'activity' && <><div className="wi-line"><h4>Latest event revisions</h4><button className="ws-text" disabled={disabled} onClick={() => void activity(view.after)}><RefreshCw size={14} aria-hidden="true" />Refresh activity</button></div><p className="ws-hint">Each event appears once with its latest revision, including pending and cancelled evidence. Identity order is not chronological order. Latest does not mean posted, active, fresh or complete.</p>
      {!view.page.items.length && <p className="wi-empty">No events on this page. Missing activity does not establish zero movements or complete account history.</p>}
      {view.page.items.map(event => item(event))}
      <div className="wi-line"><button className="ws-text" disabled={disabled || view.after === null} onClick={() => void activity()}>First activity page</button><button className="ws-text" disabled={disabled || !view.page.next_after} onClick={() => void activity(view.page.next_after)}>Next activity page<ArrowRight size={14} aria-hidden="true" /></button></div></>}
    {view?.kind === 'history' && <><button className="ws-text" disabled={disabled} onClick={() => void activity()}>Back to current activity</button><h4>Event revision history</h4><p className="ws-hint">Newest revisions first. Source, coverage, dates and values can change between revisions. This live read may include a newer revision than the event you opened. Earlier pages are replaced, not accumulated.</p>
      {!view.page.items.length && <p className="wi-empty">No revisions on this page. This does not establish complete event or account history.</p>}
      {view.page.items.map(event => item(event, true))}
      <div className="wi-line"><button className="ws-text" disabled={disabled || view.before === null} onClick={() => void history(view.root)}>Latest event revisions</button><button className="ws-text" disabled={disabled || !view.page.next_before} onClick={() => void history(view.root, view.page.next_before)}>Earlier event revisions</button></div></>}
    {view?.kind === 'coverage' && <><button className="ws-text" disabled={disabled} onClick={() => void activity()}>Back to current activity</button><h4>Source coverage for event</h4><p className="wi-scope">Event {view.source.event_id} · revision {view.source.revision}<br />Source {view.source.source_id}</p><p className="ws-hint">These are the selected source's reported periods and replacement history. The source can cover other positions or events. Claims do not prove a completed or reconciled import, and overlapping periods are not combined.</p>
      {!view.page.items.length && <p className="wi-empty">No source observations on this page. History coverage remains unknown.</p>}
      {view.page.items.map(source => <article className="wi-evidence" key={source.id}><div className="wi-line"><h4>{coverageLabels[source.coverage]}</h4><span className="ws-pill">{source.is_current ? 'Current evidence version' : 'Superseded evidence'}</span></div><dl className="wi-meta"><div><dt>Reported period</dt><dd>{source.period_start ? `${source.period_start} to ${source.period_end}` : 'Not supplied'}</dd></div><div><dt>Observation</dt><dd>{source.id}</dd></div>{source.previous_id && <div><dt>Replaces</dt><dd>{source.previous_id}</dd></div>}</dl><p className="ws-hint">{source.coverage === 'complete_activity' ? 'The source claims complete activity only for this supplied period. Reconciled completion must be checked separately.' : source.coverage === 'snapshot' ? 'A snapshot cannot establish a transaction ledger.' : source.coverage === 'partial_activity' ? 'History outside this evidence remains missing or unverified.' : 'This source has not established its activity coverage.'} Current evidence does not mean fresh or complete.</p></article>)}
      <div className="wi-line"><button className="ws-text" disabled={disabled || view.after === null} onClick={() => void coverage(view.source)}>First source page</button><button className="ws-text" disabled={disabled || !view.page.next_after} onClick={() => void coverage(view.source, view.page.next_after)}>Next source page</button></div></>}
  </section>
}
