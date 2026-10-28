import { useEffect, useRef, useState } from 'react'
import { ArrowLeft, ArrowRight, History, RefreshCw } from 'lucide-react'
import type { AuthController, Screen } from './auth'
import type { BankAccount } from './banking-evidence'
import { exactValue } from './investments'
import { cashChoicePage, cashResolution, cashScope, cashSelectionHistory, cashSnapshotHistory, emptyCashChoices, latestCashHistory, MAX_CASH_PAGES, MAX_CASH_ROOTS, observeSelection, observeSnapshot, pinnedCashHistory } from './bank-cash-evidence'
import type { CashHistory, CashResolution, CashScope, CashSelection, CashSnapshot, HistoryRead, NativeCurrency } from './bank-cash-evidence'
import './bank-cash.css'

type ChoiceReturn = { kind: 'choices'; origin: CashSelection; read: HistoryRead; pages: number }
type Return = ChoiceReturn | { kind: 'resolved'; origin: CashSelection }
type View = { kind: 'absent' } | { kind: 'resolved'; origin: CashSelection; result: CashResolution }
  | { kind: 'choices'; origin: CashSelection; read: HistoryRead; page: CashHistory<CashSelection>; pages: number }
  | { kind: 'snapshots'; pin: CashSelection; origin: CashSnapshot; read: HistoryRead; page: CashHistory<CashSnapshot>; back: Return; pages: number }
const states = {
  selected: ['Selected cash snapshot', 'A dated source choice, checked against its retained evidence.'],
  unselected: ['Saved cash choice cleared', 'This choice was explicitly cleared. Earlier choices remain in history.'],
  stale: ['Saved cash choice needs review', 'Its pinned revision or source review context changed. This state does not describe the age of the report.'],
  cancelled: ['Selected evidence is cancelled', 'This choice has no usable cash amount. Retained revisions remain inspectable.'],
  archived: ['Cash choice belongs to an archived account', 'Retained history can still be inspected; no usable cash amount is shown.'],
  conflicting: ['Saved cash evidence conflicts', 'Comparable evidence disagrees. This choice has no usable cash amount.'],
} as const
const reasons = { reviewed: 'Reviewed choice', newer_evidence: 'Newer evidence chosen', correction: 'Choice corrected', clear: 'Choice cleared' }
const corrections = { source_correction: 'Source correction', cancellation: 'Cancellation', reinstatement: 'Reinstatement' }
const coverage = { snapshot: 'Snapshot evidence only', partial_activity: 'Partial activity reported', complete_activity: 'Source claims complete activity', unknown: 'Coverage unknown' }
function SnapshotDetails({ item, masked, historical }: { item: CashSnapshot; masked: boolean; historical: boolean }) {
  return <article className="wb-cash-snapshot">
    {historical && <div className="wb-line"><h4>Snapshot revision {item.revision}</h4><span className="ws-pill">Retained evidence</span></div>}
    {historical && <p className="ws-hint">{item.is_current ? 'Latest retained revision' : 'Earlier retained revision'} · {item.correction_reason ? corrections[item.correction_reason] : 'Original evidence'} · {item.account_state === 'archived' ? 'Archived account' : 'Active account'}</p>}
    {item.status === 'active' ? <dl className="wb-cash-value"><div><dt>{historical ? 'Historical native cash' : 'Reported native cash'}</dt><dd>{exactValue(item.components[0]!, masked)}</dd></div><div><dt>As reported on</dt><dd>{item.as_of_instant ?? item.as_of_date}</dd></div></dl> : <p className="ws-notice">Cancelled snapshot. This revision has no amount; it does not record zero cash.</p>}
    <details className="wb-about"><summary>Snapshot provenance · revision {item.revision}</summary><dl className="wb-meta">
      <div><dt>Reported scope</dt><dd>{item.snapshot_scope === null ? 'Not supplied' : item.snapshot_scope === 'native_cash' ? 'Native cash' : 'Full account reported'}</dd></div>
      <div><dt>Reported coverage</dt><dd>{coverage[item.coverage]}</dd></div><div><dt>Reported period</dt><dd>{item.period_start ? `${item.period_start} to ${item.period_end}` : 'Not supplied'}</dd></div>
      <div><dt>Calendar as-of date</dt><dd>{item.as_of_date ?? 'Not supplied'}</dd></div><div><dt>Original as-of instant</dt><dd>{item.as_of_instant ?? 'Not supplied'}</dd></div>
      <div><dt>Booking date</dt><dd>{item.booking_date ?? 'Not supplied'}</dd></div><div><dt>Cash date basis</dt><dd>{item.cash_date_basis ?? 'Not supplied'}</dd></div><div><dt>Statement boundary</dt><dd>{item.reconciliation_boundary?.replaceAll('_', ' ') ?? 'Not supplied'}</dd></div>
      {([['Snapshot', item.id], ['Source', item.source_id], ['Observation', item.observation_id], ['Batch', item.batch_id], ['Source row', item.source_row_id], ['Source review revision', item.source_review_revision]] as const).map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}
    </dl><p className="ws-hint">These facts belong to this snapshot revision. Coverage and scope do not establish complete account history or a live bank connection.</p></details>
  </article>
}
function ChoiceDetails({ item }: { item: CashSelection }) {
  return <details className="wb-about"><summary>Choice details · revision {item.revision}</summary><dl className="wb-meta"><div><dt>Choice</dt><dd>{item.id}</dd></div><div><dt>Snapshot</dt><dd>{item.snapshot_id ?? 'Choice cleared'}</dd></div><div><dt>Pinned revision</dt><dd>{item.snapshot_revision ?? 'No pinned revision'}</dd></div></dl></details>
}
export default function BankCashWorkspace({ auth, screen, busy, account, onBack, onUnavailable }: { auth: AuthController; screen: Extract<Screen, { kind: 'workspace' }>; busy: boolean; account: BankAccount; onBack: () => void; onUnavailable: () => void }) {
  const [currency, setCurrency] = useState<NativeCurrency | ''>(account.currencies.length === 1 ? account.currencies[0]! : ''), [view, setView] = useState<View>(), [loading, setLoading] = useState(false)
  const mounted = useRef(true), generation = useRef(0), heading = useRef<HTMLHeadingElement>(null)
  const selectionHead = useRef<CashSelection | undefined>(undefined), snapshotHeads = useRef(new Map<string, CashSnapshot>()), archived = useRef(account.state === 'archived')
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; generation.current++ } }, [])
  useEffect(() => { heading.current?.focus() }, [view, loading])
  const disabled = busy || loading, masked = screen.preferences.amount_masked
  const work = async (read: (live: () => boolean) => Promise<View | undefined>) => {
    const token = ++generation.current, live = () => mounted.current && token === generation.current
    setView(undefined); setLoading(true)
    try { const next = await read(live); if (live()) setView(next) }
    catch { if (live()) onUnavailable() }
    finally { if (live()) setLoading(false) }
  }
  const scopeFor = () => cashScope(archived.current ? { ...account, state: 'archived' } : account, currency)
  const rememberSnapshot = (item: CashSnapshot) => { snapshotHeads.current.set(item.id, observeSnapshot(snapshotHeads.current.get(item.id), item)); if (item.account_state === 'archived') archived.current = true }
  const resolveRead = async (scope: CashScope, origin: CashSelection, live: () => boolean): Promise<View | undefined> => {
    const head = selectionHead.current ?? origin
    const result = await auth.finance('/snapshots/selections/resolve', { id: origin.id }, value => {
      if (!live()) return undefined
      // A different selected root has its own floor; never transfer another root's revision.
      const resolved = cashResolution(value, scope, origin, head)
      if (resolved.snapshot) {
        const prior = snapshotHeads.current.get(resolved.snapshot.id)
        if (!prior && snapshotHeads.current.size >= MAX_CASH_ROOTS) throw new Error('Cash inspection limit reached')
        observeSnapshot(prior, resolved.snapshot)
      }
      return resolved
    })
    if (!result || !live()) return
    selectionHead.current = observeSelection(head, result.selection)
    if (result.state === 'archived') archived.current = true
    if (result.snapshot) rememberSnapshot(result.snapshot)
    return { kind: 'resolved', origin, result }
  }
  const discover = () => work(async live => {
    const scope = scopeFor()
    let after: string | null = null, progress = emptyCashChoices, found: CashSelection | undefined
    do {
      const result: ReturnType<typeof cashChoicePage> | undefined = await auth.finance('/snapshots/selections/query', { account_id: account.id, limit: 25, after }, value => { if (!live()) return undefined; const parsed = cashChoicePage(value, scope.account, after, progress); for (const item of parsed.items) if (item.currency === scope.currency && selectionHead.current) observeSelection(selectionHead.current, item); return parsed })
      if (!result || !live()) return
      // All account rows, including another declared currency, have been validated.
      const match = result.items.find(item => item.currency === scope.currency)
      if (match) found = match
      progress = result.progress; after = result.next_after
      if (after !== null && progress.pages >= MAX_CASH_PAGES) throw new Error('Cash discovery is incomplete')
    } while (after !== null)
    if (!found) return { kind: 'absent' }
    selectionHead.current = observeSelection(selectionHead.current, found)
    return resolveRead(scope, found, live)
  })
  const resolve = (origin: CashSelection) => work(live => resolveRead(scopeFor(), origin, live))
  const choices = (origin: CashSelection, read: HistoryRead = latestCashHistory, pages = 0) => work(async live => {
    const scope = scopeFor(), head = selectionHead.current ?? origin
    const page = await auth.finance('/snapshots/selections/history', { id: origin.id, limit: 25, before: read.before }, value => live() ? cashSelectionHistory(value, scope, origin, head, read) : undefined)
    if (!page || !live()) return
    for (const item of page.items) selectionHead.current = observeSelection(selectionHead.current, item)
    return { kind: 'choices', origin, read, page, pages }
  })
  const snapshots = (pin: CashSelection, back: Return, read = pinnedCashHistory(pin.snapshot_revision!), pages = 0, original?: CashSnapshot) => work(async live => {
    if (!pin.snapshot_id || pin.snapshot_revision === null) throw new Error('No pinned snapshot')
    const scope = scopeFor(), target = { id: pin.snapshot_id, revision: pin.snapshot_revision }, head = snapshotHeads.current.get(target.id)
    const page = await auth.finance('/snapshots/history', { id: target.id, limit: 25, before: read.before }, value => {
      if (!live()) return undefined
      if (!head && snapshotHeads.current.size >= MAX_CASH_ROOTS) throw new Error('Cash inspection limit reached')
      return cashSnapshotHistory(value, scope, target, head, read, original)
    })
    if (!page || !live()) return
    for (const item of page.items) rememberSnapshot(item)
    const origin = original ?? page.items[0]!
    return { kind: 'snapshots', pin, origin, read, page, back, pages }
  })
  const clearScope = (next: NativeCurrency | '') => {
    generation.current++; selectionHead.current = undefined; snapshotHeads.current.clear(); setView(undefined); setLoading(false); setCurrency(next)
  }
  const returnFromSnapshot = (back: Return) => back.kind === 'choices' ? choices(back.origin, back.read, back.pages) : resolve(back.origin)
  const resolved = view?.kind === 'resolved' ? view.result : undefined
  return <div className="wb-cash" aria-busy={loading}>
    <div className="wb-line"><button className="ws-text" disabled={disabled} onClick={onBack}><ArrowLeft size={15} aria-hidden="true" />Choose another bank account</button>{view && <button className="ws-text" disabled={disabled} onClick={() => clearScope('')}>Choose native currency</button>}</div>
    <h3 ref={heading} tabIndex={-1}>{loading ? 'Checking saved cash evidence…' : view?.kind === 'choices' ? 'Cash choice history' : view?.kind === 'snapshots' ? 'Retained cash snapshot revisions' : resolved ? states[resolved.state][0] : view?.kind === 'absent' ? 'No saved cash choice' : 'Inspect a native cash choice'}</h3>
    <p className="ws-hint">Dated source evidence. No live or available bank balance is calculated. Your {screen.preferences.display_currency} display preference does not convert these native values.</p>
    {archived.current && <p className="ws-notice">This bank account is archived. Retained choices and historical reports remain inspectable.</p>}
    {currency && <p className="wb-cash-native">Native currency · <strong>{currency}</strong></p>}
    {loading && <p role="status" className="wb-message">Checking this account’s saved choice and evidence.</p>}
    {!loading && !view && <form className="wb-cash-choose" onSubmit={event => { event.preventDefault(); void discover() }}><label htmlFor="bank-cash-currency">Native currency</label><select id="bank-cash-currency" value={currency} disabled={disabled} onChange={event => clearScope(event.target.value as NativeCurrency | '')}><option value="">Choose a native currency</option>{account.currencies.map(native => <option key={native} value={native}>{native}</option>)}</select><button className="ws-secondary" disabled={disabled || !currency} type="submit">View saved cash choice<ArrowRight size={15} aria-hidden="true" /></button></form>}
    {view?.kind === 'absent' && <div className="wb-message"><p>No saved source choice was found for {currency}. This does not establish zero cash; retained reports may exist.</p><button className="ws-text" disabled={disabled} onClick={() => void discover()}><RefreshCw size={15} aria-hidden="true" />Check saved choices again</button></div>}
    {view?.kind === 'resolved' && <><p className="ws-hint">{states[view.result.state][1]}</p>{view.result.selection.revision > view.origin.revision && <p className="wb-origin">The saved choice changed since it was opened. Showing choice revision {view.result.selection.revision}.</p>}
      {view.result.snapshot && <SnapshotDetails item={view.result.snapshot} masked={masked} historical={false} />}
      <p className="ws-hint">Choice revision {view.result.selection.revision} · {reasons[view.result.selection.reason]}</p>
      <ChoiceDetails item={view.result.selection} /><div className="wb-cash-actions">
        <button className="ws-text" disabled={disabled} onClick={() => void resolve(view.origin)}><RefreshCw size={15} aria-hidden="true" />Refresh saved choice</button>
        <button className="ws-text" disabled={disabled} onClick={() => void choices(view.origin)}><History size={15} aria-hidden="true" />Choice history</button>
        {view.result.selection.snapshot_id && <button className="ws-text" disabled={disabled} onClick={() => void snapshots(view.result.selection, { kind: 'resolved', origin: view.origin }, pinnedCashHistory(view.result.selection.snapshot_revision!), 0, view.result.snapshot ?? undefined)}>Inspect pinned snapshot<ArrowRight size={15} aria-hidden="true" /></button>}
      </div></>}
    {view?.kind === 'choices' && <><div className="wb-line"><button className="ws-text" disabled={disabled} onClick={() => void resolve(view.origin)}><ArrowLeft size={15} aria-hidden="true" />Back to saved cash</button><button className="ws-text" disabled={disabled} onClick={() => void choices(view.origin, view.read, view.pages)}><RefreshCw size={15} aria-hidden="true" />Refresh choice history</button></div><p className="ws-hint">These revisions record saved choices, not whether those choices are usable now.</p>
      {view.page.items.map(item => <article className="wb-event" key={item.revision}><div className="wb-line"><h4>Choice revision {item.revision}</h4><span className="ws-pill">{reasons[item.reason]}</span></div><p className="ws-hint">{item.is_current ? 'Latest saved choice' : 'Earlier saved choice'} · {item.currency}</p><ChoiceDetails item={item} />{item.snapshot_id && <button className="ws-text" disabled={disabled} aria-label={`Inspect pinned snapshot for choice revision ${item.revision}`} onClick={() => void snapshots(item, { kind: 'choices', origin: view.origin, read: view.read, pages: view.pages })}>Inspect pinned snapshot<ArrowRight size={15} aria-hidden="true" /></button>}</article>)}
      <div className="wb-line"><button className="ws-text" disabled={disabled || view.read.mode === 'latest'} onClick={() => void choices(view.origin)}>Latest choice revisions</button><button className="ws-text" disabled={disabled || view.page.next_before === null || view.pages >= MAX_CASH_PAGES - 1} onClick={() => void choices(view.origin, { mode: 'earlier', before: view.page.next_before! }, view.pages + 1)}>Earlier choices<ArrowRight size={15} aria-hidden="true" /></button></div>{view.pages >= MAX_CASH_PAGES - 1 && view.page.next_before && <p className="ws-notice">The inspection page limit was reached. History remains incomplete.</p>}
    </>}
    {view?.kind === 'snapshots' && <><div className="wb-line"><button className="ws-text" disabled={disabled} onClick={() => void returnFromSnapshot(view.back)}><ArrowLeft size={15} aria-hidden="true" />Back to {view.back.kind === 'choices' ? 'choice history' : 'saved cash'}</button><button className="ws-text" disabled={disabled} onClick={() => void snapshots(view.pin, view.back, view.read, view.pages, view.origin)}><RefreshCw size={15} aria-hidden="true" />Refresh snapshot revisions</button></div>
      <p className="ws-notice">Historical inspection · Choice revision {view.pin.revision} pinned snapshot revision {view.pin.snapshot_revision}. These retained amounts do not supply the selected cash view.</p>
      {view.page.items.map(item => <div key={item.revision}>{item.revision === view.pin.snapshot_revision && <p className="wb-origin">Pinned by the opened choice</p>}<SnapshotDetails item={item} masked={masked} historical /></div>)}
      <div className="wb-cash-actions"><button className="ws-text" disabled={disabled || view.read.mode === 'pin'} onClick={() => void snapshots(view.pin, view.back, pinnedCashHistory(view.pin.snapshot_revision!), 0, view.origin)}>Pinned snapshot revision</button><button className="ws-text" disabled={disabled || view.read.mode === 'latest'} onClick={() => void snapshots(view.pin, view.back, latestCashHistory, 0, view.origin)}>Latest snapshot revisions</button><button className="ws-text" disabled={disabled || view.page.next_before === null || view.pages >= MAX_CASH_PAGES - 1} onClick={() => void snapshots(view.pin, view.back, { mode: 'earlier', before: view.page.next_before! }, view.pages + 1, view.origin)}>Earlier snapshots<ArrowRight size={15} aria-hidden="true" /></button></div>{view.pages >= MAX_CASH_PAGES - 1 && view.page.next_before && <p className="ws-notice">The inspection page limit was reached. History remains incomplete.</p>}
    </>}
  </div>
}
