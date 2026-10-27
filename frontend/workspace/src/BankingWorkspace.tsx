import { useEffect, useRef, useState } from 'react'
import { ArrowLeft, ArrowRight, History, Landmark, RefreshCw } from 'lucide-react'
import type { AuthController, Screen } from './auth'
import { ACCOUNT_PAGE_SIZE, MAX_ACCOUNT_PAGES } from './accounts'
import type { AccountCursor, AccountPage } from './accounts'
import { bankAccountPage, bankActivityPage, bankHistory } from './banking-evidence'
import type { BankAccount } from './banking-evidence'
import { eventIdentity, eventRoles } from './activity-evidence'
import type { ActivityHistory, EventEvidence, EventIdentity } from './activity-evidence'
import { exactValue } from './investments'
import ReceiptInspection from './ReceiptInspection'
import { receiptPage } from './receipt-evidence'
import type { SavedReceipt } from './receipt-evidence'
import BankSourceRecords from './BankSourceRecords'
import { bankCoverageLabels, bankProvenance, bankSourcePage, emptySourceProgress } from './bank-provenance'
import type { BankProvenance, BankSourcePage, SourceProgress } from './bank-provenance'
import type { Page } from './investments'
import './investments.css'
import './banking.css'

type View = { kind: 'source'; account: BankAccount; context: BankProvenance; page: BankSourcePage; after: string | null; preceding: SourceProgress }
  | { kind: 'receipt'; account: BankAccount; context: BankProvenance; page: Page<SavedReceipt> }
  | { kind: 'accounts'; page: AccountPage; cursor: AccountCursor }
  | { kind: 'activity'; account: BankAccount; page: Page<EventEvidence>; after: string | null }
  | { kind: 'history'; account: BankAccount; root: EventIdentity; page: ActivityHistory; before: number | null }
const institutions = { hdfc: 'HDFC', sbi: 'SBI' }
const kinds = { cash_movement: 'Cash movement', fee: 'Fee', withholding: 'Withholding' }
const roles = { net_cash: 'Net cash movement', fee: 'Supplied fee', withholding: 'Supplied withholding' }
const reasons = { source_correction: 'Source correction', posting_update: 'Posting update', cancellation: 'Cancellation', reinstatement: 'Reinstatement' }
function BankEvent({ item, masked, disabled, onHistory, onSource, onReceipt }: { item: EventEvidence; masked: boolean; disabled: boolean; onHistory?: () => void; onSource: () => void; onReceipt: () => void }) {
  return <article className="wb-event"><div className="wb-line"><h3>{kinds[item.kind as keyof typeof kinds]}</h3><span className="ws-pill">{item.posting_state === 'posted' ? 'Posted' : 'Pending'} · {item.status === 'active' ? 'Active evidence' : 'Cancelled evidence'}</span></div>
    <p className="ws-hint">{item.is_current ? 'Latest retained revision' : 'Earlier retained revision'} {item.revision} · {item.correction_reason ? reasons[item.correction_reason] : 'Original evidence'} · {item.account_state === 'archived' ? 'Archived account' : 'Active account'}</p>
    {item.status === 'cancelled' ? <p className="ws-notice">Cancelled record. This revision has no amounts; earlier amounts remain in history.</p>
      : <dl className="wb-values">{eventRoles[item.kind].map(role => { const value = item.components.find(value => value.role === role); return <div key={role}><dt>{roles[role as keyof typeof roles]}</dt><dd>{masked ? '••••' : value ? exactValue(value, false) : 'Not supplied by this revision'}</dd></div> })}</dl>}
    <dl className="wb-dates"><div><dt>Booking date</dt><dd>{item.booking_date ?? 'Not supplied'}</dd></div><div><dt>Value date</dt><dd>{item.value_date ?? 'Not supplied'}</dd></div><div><dt>Cash date basis</dt><dd>{item.cash_date_basis ?? 'Not supplied'}</dd></div></dl>
    {item.posting_state === 'pending' && <p className="ws-hint">Pending evidence is not a posted movement.</p>}<div className="wb-event-actions"><details><summary>Source details</summary><dl className="wb-meta"><div><dt>Trade date</dt><dd>{item.trade_date ?? 'Not supplied'}</dd></div><div><dt>Settlement date</dt><dd>{item.settlement_date ?? 'Not supplied'}</dd></div><div><dt>Reported coverage</dt><dd>{bankCoverageLabels[item.coverage]}</dd></div><div><dt>Reported period</dt><dd>{item.period_start ? `${item.period_start} to ${item.period_end}` : 'Not supplied'}</dd></div><div><dt>Event</dt><dd>{item.id}</dd></div><div><dt>Source</dt><dd>{item.source_id}</dd></div><div><dt>Observation</dt><dd>{item.observation_id}</dd></div><div><dt>Batch</dt><dd>{item.batch_id}</dd></div><div><dt>Source row</dt><dd>{item.source_row_id}</dd></div><div><dt>Source review revision</dt><dd>{item.source_review_revision}</dd></div></dl><p className="ws-hint">These fields belong to this revision. Coverage is a source claim, not proof of reconciliation or complete account history. A cancelled record does not create a reversal or zero movement.</p><div className="wb-provenance-actions"><button className="ws-text" disabled={disabled} aria-label={`Source records for event ${item.id}, revision ${item.revision}`} onClick={onSource}>Source records<ArrowRight size={15} aria-hidden="true" /></button><button className="ws-text" disabled={disabled} aria-label={`Batch receipts for event ${item.id}, revision ${item.revision}`} onClick={onReceipt}>Batch receipts<ArrowRight size={15} aria-hidden="true" /></button></div></details>
    {onHistory && <button className="ws-text" disabled={disabled} aria-label={`Revision history for event ${item.id}`} onClick={onHistory}><History size={15} aria-hidden="true" />Revision history</button>}</div>
  </article>
}
export default function Banking({ auth, screen, busy }: { auth: AuthController; screen: Extract<Screen, { kind: 'workspace' }>; busy: boolean }) {
  const [view, setView] = useState<View>(), [loading, setLoading] = useState(true), [failed, setFailed] = useState(false)
  const started = useRef(false), mounted = useRef(true), generation = useRef(0), heading = useRef<HTMLHeadingElement>(null)
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; generation.current++ } }, [])
  useEffect(() => { if (view?.kind !== 'receipt') heading.current?.focus() }, [view, loading, failed])
  const disabled = busy || loading, masked = screen.preferences.amount_masked
  const work = async (read: () => Promise<View | undefined>) => {
    const current = ++generation.current; setView(undefined); setLoading(true); setFailed(false)
    try { const next = await read(); if (mounted.current && current === generation.current) setView(next) }
    catch { if (mounted.current && current === generation.current) setFailed(true) }
    finally { if (mounted.current && current === generation.current) setLoading(false) }
  }
  const directory = (cursor: AccountCursor = { after: null, previous: [] }) => work(async () => {
    const page = await auth.finance('/accounts/query', { limit: ACCOUNT_PAGE_SIZE, after: cursor.after }, value => bankAccountPage(value, cursor.after))
    return page && { kind: 'accounts', page, cursor }
  })
  useEffect(() => {
    if (started.current || busy) return
    let cancelled = false
    queueMicrotask(() => {
      if (cancelled || started.current || auth.snapshot().busy) return
      started.current = true
      void directory()
    })
    return () => { cancelled = true }
  }, [auth, busy])
  const activity = (account: BankAccount, after: string | null = null) => work(async () => {
    const page = await auth.finance('/events/query', { account_id: account.id, limit: 25, after }, value => bankActivityPage(value, account, after))
    return page && { kind: 'activity', account, page, after }
  })
  const history = (account: BankAccount, root: EventIdentity, before: number | null = null) => work(async () => {
    const page = await auth.finance('/events/history', { id: root.id, limit: 25, before }, value => bankHistory(value, account, root, before))
    return page && { kind: 'history', account, root, page, before }
  })
  const resetFailure = () => { if (!mounted.current) return; generation.current++; setView(undefined); setLoading(false); setFailed(true) }
  const readSource = async (context: BankProvenance, after: string | null = null, preceding: SourceProgress = emptySourceProgress): Promise<View | undefined> => {
    const page = await auth.finance('/imports/observations/query', { source_id: context.origin.source_id, limit: 25, after }, value => bankSourcePage(value, context.origin, after, preceding))
    return page && { kind: 'source', account: context.account, context, page, after, preceding }
  }
  const source = (context: BankProvenance, after: string | null, preceding: SourceProgress) => work(() => readSource(context, after, preceding))
  const openSource = (account: BankAccount, item: EventEvidence, root?: EventIdentity) => work(() => readSource(bankProvenance(account, item, root)))
  const completion = (account: BankAccount, item: EventEvidence, root?: EventIdentity) => work(async () => {
    const context = bankProvenance(account, item, root)
    const page = await auth.finance('/receipts/query', { batch_id: context.origin.batch_id, limit: 25, after: null }, value => receiptPage(value, context.origin))
    return page && { kind: 'receipt', account: context.account, context, page }
  })
  const returnToRecord = (context: BankProvenance) => context.back.kind === 'history' ? history(context.account, context.back.root) : activity(context.account)
  const eligible = view?.kind === 'accounts' ? view.page.items.filter((account): account is BankAccount => account.kind === 'bank') : []
  return <section className="wb-workspace" aria-labelledby="banking-heading" aria-busy={loading}><div className="wb-title"><div><span className="ws-eyebrow">Saved evidence, in context</span><h2 id="banking-heading" ref={heading} tabIndex={-1}>{view?.kind === 'source' ? 'Source records' : view?.kind === 'receipt' ? 'Import details' : view?.kind === 'history' ? 'Event revision history' : view?.kind === 'activity' ? 'Saved account activity' : 'Your bank accounts'}</h2><p>{view && view.kind !== 'accounts' ? `${institutions[view.account.institution]} · ${view.account.label}` : 'Inspect saved HDFC and SBI accounts and their activity.'}</p></div><Landmark size={30} aria-hidden="true" /></div>
    <p className="wb-native">Saved records · Amounts shown in their original currencies.</p>
    {loading && <p className="wb-message" role="status">Checking saved bank evidence…</p>}
    {failed && <div className="wb-message" role="alert"><strong>Bank evidence could not be verified.</strong><p>Previous values and account context have been cleared.</p><button className="ws-secondary" disabled={disabled} onClick={() => void directory()}>Reload saved bank accounts</button></div>}
    {view?.kind === 'accounts' && <><div className="wb-line"><h3>Saved bank accounts on this page</h3><button className="ws-text" disabled={disabled} onClick={() => void directory(view.cursor)}><RefreshCw size={15} aria-hidden="true" />Refresh accounts</button></div><p className="ws-hint">HDFC and SBI bank accounts on this page. Other pages may contain more.</p>
      {!eligible.length && <p className="wb-message">No HDFC or SBI bank accounts on this page. This does not establish that no bank accounts are saved.</p>}
      <ul className="wb-accounts" aria-label="Saved bank accounts">{eligible.map(account => <li key={account.id}><span className="ws-eyebrow">{institutions[account.institution]}</span><h4>{account.label}</h4><p>{account.currencies.join(' · ')} native · {account.state === 'active' ? 'Active' : 'Archived'}</p><button className="ws-secondary" disabled={disabled} aria-label={`View saved activity for ${institutions[account.institution]} ${account.label}`} onClick={() => void activity(account)}>View saved activity<ArrowRight size={15} aria-hidden="true" /></button></li>)}</ul>
      <p className="ws-hint" role="status">Account directory page {view.cursor.previous.length + 1} · {eligible.length} bank accounts shown from {view.page.items.length} saved accounts</p><div className="wb-line"><button className="ws-text" disabled={disabled || !view.cursor.previous.length} onClick={() => void directory({ after: view.cursor.previous.at(-1)!, previous: view.cursor.previous.slice(0, -1) })}><ArrowLeft size={15} aria-hidden="true" />Previous account page</button><button className="ws-text" disabled={disabled || !view.page.next_after || view.cursor.previous.length >= MAX_ACCOUNT_PAGES - 1} onClick={() => void directory({ after: view.page.next_after, previous: [...view.cursor.previous, view.cursor.after] })}>Next account page<ArrowRight size={15} aria-hidden="true" /></button></div>{view.cursor.after && <button className="ws-text" disabled={disabled} onClick={() => void directory()}>First account page</button>}{view.cursor.previous.length >= MAX_ACCOUNT_PAGES - 1 && view.page.next_after && <p className="ws-notice">This view reached its page limit. Some accounts are not displayed.</p>}</>}
    {view?.kind === 'source' && <BankSourceRecords context={view.context} page={view.page} after={view.after} preceding={view.preceding} disabled={disabled} onBack={() => void returnToRecord(view.context)} onPage={(after, preceding) => void source(view.context, after, preceding)} />}
    {view?.kind === 'receipt' && <ReceiptInspection auth={auth} context={view.context.origin} initial={view.page} masked={masked} busy={busy} navigation={{ mode: 'bank-comparisons', context: view.context, onUnavailable: resetFailure, backLabel: view.context.back.kind === 'history' ? 'revision history' : 'saved activity' }} onBack={() => void returnToRecord(view.context)} />}
    {(view?.kind === 'activity' || view?.kind === 'history') && <><div className="wb-line"><button className="ws-text" disabled={disabled} onClick={() => view.kind === 'history' ? void activity(view.account) : void directory()}><ArrowLeft size={15} aria-hidden="true" />{view.kind === 'history' ? 'Back to saved activity' : 'Choose another bank account'}</button><button className="ws-text" disabled={disabled} onClick={() => view.kind === 'history' ? void history(view.account, view.root, view.before) : void activity(view.account, view.after)}><RefreshCw size={15} aria-hidden="true" />{view.kind === 'history' ? 'Refresh revisions' : 'Refresh activity'}</button></div>
      <details className="wb-about"><summary>{view.kind === 'history' ? 'About revision history' : 'About saved activity'}</summary><p className="ws-hint">{view.kind === 'history' ? 'Newest retained revisions first. Newer revisions than the one opened may appear; source details, dates and values can change.' : 'Each event appears once at its latest retained revision. Identity order is not date order, and latest does not mean posted, active, fresh or complete.'}</p><p className="ws-hint">This view reads saved records without a live bank connection and does not calculate balances. Your {screen.preferences.display_currency} display preference does not convert this native evidence. Spending, income and matched transfers are not inferred.</p></details>
      {!view.page.items.length && <p className="wb-message">{view.kind === 'activity' ? 'No saved events on this page.' : 'No earlier revisions on this page.'} This does not establish a zero balance or complete history.</p>}
      {view.page.items.map(item => <BankEvent key={`${item.id}-${item.revision}`} item={item} masked={masked} disabled={disabled} onHistory={view.kind === 'activity' ? () => void history(view.account, eventIdentity(item)) : undefined} onSource={() => void openSource(view.account, item, view.kind === 'history' ? view.root : undefined)} onReceipt={() => void completion(view.account, item, view.kind === 'history' ? view.root : undefined)} />)}
      {view.kind === 'activity' ? <div className="wb-line"><button className="ws-text" disabled={disabled || view.after === null} onClick={() => void activity(view.account)}>First activity page</button><button className="ws-text" disabled={disabled || !view.page.next_after} onClick={() => void activity(view.account, view.page.next_after)}>Next activity page<ArrowRight size={15} aria-hidden="true" /></button></div> : <div className="wb-line"><button className="ws-text" disabled={disabled || view.before === null} onClick={() => void history(view.account, view.root)}>Latest revisions</button><button className="ws-text" disabled={disabled || !view.page.next_before} onClick={() => void history(view.account, view.root, view.page.next_before)}>Earlier revisions<ArrowRight size={15} aria-hidden="true" /></button></div>}
    </>}
  </section>
}
