import { useEffect, useRef, useState } from 'react'
import { ArrowLeft, ArrowRight, FileSearch, History, RefreshCw } from 'lucide-react'
import type { AuthController, Screen } from './auth'
import { CREDIT_MAX_PAGES, CREDIT_PAGE_SIZE } from './credit-identities'
import type { CreditAccount, CreditCursor, CreditPage } from './credit-identities'
import { creditCashLabel, creditEvidenceHistory, creditEvidenceInspection, creditEvidencePage, creditKindNames, creditRoleNames, creditTreatmentNames } from './credit-evidence'
import type { CreditCash, CreditEvidence, CreditEvidenceHistory, CreditKind } from './credit-evidence'
import './credit-evidence.css'

type View =
  | { kind: 'page'; page: CreditPage<CreditEvidence>; cursor: CreditCursor }
  | { kind: 'history'; root: CreditEvidence; page: CreditEvidenceHistory; before: number | null; depth: number; minimumRevision: number }
  | { kind: 'inspect'; item: CreditEvidence; root: CreditEvidence; minimumRevision: number }
const firstPage = (): CreditCursor => ({ after: null, previous: [] })
const title = (item: CreditEvidence) => item.kind === 'statement' ? `Statement dated ${item.values.statement_date}` : item.kind === 'current' ? `Report dated ${item.values.as_of_date}` : creditRoleNames[item.values.role]
function Values({ item, masked }: { item: CreditEvidence; masked: boolean }) {
  const fields: [string, CreditCash | null][] = item.kind === 'statement' ? [['Opening liability', item.values.opening_liability], ['Closing liability', item.values.closing_liability], ['Source total due', item.values.total_due], ['Source minimum due', item.values.minimum_due]] : item.kind === 'current' ? [['Reported outstanding', item.values.outstanding], ['Reported unbilled', item.values.unbilled], ['Reported credit limit', item.values.credit_limit], ['Reported available credit', item.values.available_credit]] : [['Billed amount', item.values.billing_amount], ['Original amount', item.values.original_amount]]
  return <dl className="wce-values">{fields.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{creditCashLabel(value, masked)}</dd></div>)}</dl>
}
function EvidenceCard({ item, masked, disabled, inspect, history, detailed = false }: { item: CreditEvidence; masked: boolean; disabled: boolean; inspect?: () => void; history?: () => void; detailed?: boolean }) {
  return <article className={`wc-card wce-record${detailed ? ' wce-inspected' : ''}`}>
    <div className="wc-card-heading"><h3>{title(item)}</h3><span className="wc-state">Revision {item.revision} · {item.is_latest_revision ? 'Newest retained' : 'Earlier retained'}</span></div>
    {item.kind === 'statement' && <p className="wce-period">Billing period {item.values.period_start} to {item.values.period_end}</p>}
    {item.kind === 'entry' && <p className="wce-interpretation">{creditTreatmentNames[item.values.treatment]}</p>}
    <Values item={item} masked={masked} />
    <dl className="wc-meta wce-dates">
      {item.kind === 'statement' && <div><dt>Source due date</dt><dd>{item.values.due_date ?? 'Not supplied'}</dd></div>}
      {item.kind === 'current' && <div><dt>Source-local instant</dt><dd>{item.values.as_of_instant ?? 'Date precision only'}</dd></div>}
      {item.kind === 'entry' && <><div><dt>Transaction date</dt><dd>{item.values.transaction_date ?? 'Not supplied'}</dd></div><div><dt>Posting date</dt><dd>{item.values.posting_date ?? 'Not supplied'}</dd></div></>}
    </dl>
    {detailed && <>
      <details className="wce-provenance"><summary>Saved source and revision references</summary><dl className="wc-meta"><div><dt>Evidence reference</dt><dd>{item.id}</dd></div><div><dt>Source reference</dt><dd>{item.source_id}</dd></div><div><dt>Frozen source-link revision</dt><dd>{item.mapping_revision}</dd></div><div><dt>Billing account reference</dt><dd>{item.account_id}</dd></div><div><dt>Preceding revision</dt><dd>{item.previous_revision ?? 'None — first interpretation'}</dd></div><div><dt>Account status at read</dt><dd>{item.account_state === 'active' ? 'Active' : 'Archived'}</dd></div></dl><p className="ws-hint">These are application references, not card numbers. Later source-link changes do not rewrite this revision.</p></details>
      <p className="ws-hint">{item.kind === 'statement' ? 'Signed liabilities and source dues are independent checkpoints. A due date or due amount does not establish payment status or remaining payment.' : item.kind === 'current' ? 'These values belong to the supplied source date and instant. They are not selected account balances, and their presence does not establish freshness.' : 'Roles and treatment are saved interpretations. Pending and unsupported entries are not posted account movements; a correction is not an inferred reversal or withdrawal.'}</p>
    </>}
    <div className="wc-actions">{inspect && <button className="ws-text" disabled={disabled} aria-label={`Inspect revision ${item.revision} of evidence ${item.id}`} onClick={inspect}><FileSearch size={15} aria-hidden="true" />Inspect revision</button>}{history && <button className="ws-text" disabled={disabled} aria-label={`Revision history for evidence ${item.id}`} onClick={history}><History size={15} aria-hidden="true" />Revision history</button>}</div>
  </article>
}
export default function CreditEvidenceWorkspace({ auth, screen, busy, account, kind, onBack, onDirectory, onFailure }: { auth: AuthController; screen: Extract<Screen, { kind: 'workspace' }>; busy: boolean; account: CreditAccount; kind: CreditKind; onBack: () => void; onDirectory: () => void; onFailure: () => void }) {
  const [view, setView] = useState<View>(), [loading, setLoading] = useState(true)
  const mounted = useRef(true), started = useRef(false), generation = useRef(0), heading = useRef<HTMLHeadingElement>(null)
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; generation.current++ } }, [])
  useEffect(() => { heading.current?.focus() }, [view, loading])
  const disabled = busy || loading, masked = screen.preferences.amount_masked
  const work = async (read: () => Promise<View | undefined>) => {
    const current = ++generation.current; setView(undefined); setLoading(true)
    try { const next = await read(); if (mounted.current && current === generation.current) setView(next) }
    catch { if (mounted.current && current === generation.current) onFailure() }
    finally { if (mounted.current && current === generation.current) setLoading(false) }
  }
  const page = (cursor = firstPage()) => work(async () => {
    const result = await auth.finance('/credit/evidence/query', { account_id: account.id, kind, limit: CREDIT_PAGE_SIZE, after: cursor.after }, value => creditEvidencePage(value, account, kind, cursor.after))
    return result && { kind: 'page', page: result, cursor }
  })
  const history = (root: CreditEvidence, before: number | null = null, depth = 0, minimumRevision = root.revision) => work(async () => {
    const result = await auth.finance('/credit/evidence/history', { account_id: account.id, kind, id: root.id, limit: CREDIT_PAGE_SIZE, before }, value => creditEvidenceHistory(value, account, root, before, minimumRevision))
    return result && { kind: 'history', root, page: result, before, depth, minimumRevision: Math.max(minimumRevision, result.items[0]?.revision ?? minimumRevision) }
  })
  const inspect = (selected: CreditEvidence, root = selected, minimumRevision = root.revision) => work(async () => {
    const result = await auth.finance('/credit/evidence/inspect', { account_id: account.id, kind, id: selected.id, at_revision: selected.revision }, value => creditEvidenceInspection(value, account, selected))
    return result && { kind: 'inspect', item: result, root, minimumRevision }
  })
  useEffect(() => {
    if (started.current || busy) return
    let cancelled = false
    queueMicrotask(() => { if (cancelled || started.current || auth.snapshot().busy) return; started.current = true; void page() })
    return () => { cancelled = true }
  }, [auth, busy])
  const name = view?.kind === 'history' ? 'Evidence revision history' : view?.kind === 'inspect' ? `Retained revision ${view.item.revision}` : creditKindNames[kind]
  return <section className="wc-workspace wce-workspace" aria-labelledby="credit-evidence-heading" aria-busy={loading}>
    <div className="wc-title"><div><span className="ws-eyebrow">Saved reports, original values</span><h2 id="credit-evidence-heading" ref={heading} tabIndex={-1}>{name}</h2><p>HDFC · {account.label} · {creditKindNames[kind]}</p></div><FileSearch size={30} aria-hidden="true" /></div>
    <p className="wce-native">Unselected source evidence · Amounts remain in their original currencies.</p>
    {loading && <p className="wc-message" role="status">Checking saved credit evidence…</p>}
    {view && <>
      <div className="wc-toolbar"><button className="ws-text" disabled={disabled} onClick={onBack}><ArrowLeft size={15} aria-hidden="true" />Choose report type</button><button className="ws-text" disabled={disabled} onClick={onDirectory}>All billing accounts</button></div>
      <details className="wce-about"><summary>How to read this evidence</summary><p className="ws-hint">{view.kind === 'page' ? 'One newest stored revision per evidence reference, in reference order. This is not date order or a complete statement export.' : view.kind === 'history' ? 'Retained interpretations, newest revision first. Newer corrections may appear; original source and account identity remain bound to the selected evidence.' : 'This is the exact retained revision requested. Newer revisions may exist; inspection does not select this report for account totals.'}</p><p className="ws-hint">Saved records do not establish current balances, complete coverage, selected liability, paid or overdue status. Your {screen.preferences.display_currency} display preference does not convert native evidence. Dates and references remain visible when amounts are masked.</p></details>
      {view.kind === 'page' && <>
        <div className="wc-toolbar"><h3>Saved evidence on this page</h3><button className="ws-text" disabled={disabled} onClick={() => void page(view.cursor)}><RefreshCw size={15} aria-hidden="true" />Refresh evidence</button></div>
        {!view.page.items.length && <p className="wc-message">No saved evidence of this kind on this page. This does not establish zero debt or complete coverage.</p>}
        <div className="wce-records">{view.page.items.map(item => <EvidenceCard key={item.id} item={item} masked={masked} disabled={disabled} inspect={() => void inspect(item)} history={() => void history(item)} />)}</div>
        <p className="ws-hint" role="status">Evidence page {view.cursor.previous.length + 1} · {view.page.items.length} shown</p><div className="wc-toolbar"><button className="ws-text" disabled={disabled || !view.cursor.previous.length} onClick={() => void page({ after: view.cursor.previous.at(-1)!, previous: view.cursor.previous.slice(0, -1) })}><ArrowLeft size={15} aria-hidden="true" />Previous evidence page</button><button className="ws-text" disabled={disabled || !view.page.next_after || view.cursor.previous.length >= CREDIT_MAX_PAGES - 1} onClick={() => void page({ after: view.page.next_after, previous: [...view.cursor.previous, view.cursor.after] })}>Next evidence page<ArrowRight size={15} aria-hidden="true" /></button></div>
        {view.cursor.after && <button className="ws-text" disabled={disabled} onClick={() => void page()}>First evidence page</button>}{view.page.next_after && view.cursor.previous.length >= CREDIT_MAX_PAGES - 1 && <p className="ws-notice">This view reached its page limit. More evidence may be saved.</p>}
      </>}
      {view.kind === 'history' && <>
        <div className="wc-toolbar"><button className="ws-text" disabled={disabled} onClick={() => void page()}><ArrowLeft size={15} aria-hidden="true" />Back to evidence list</button><button className="ws-text" disabled={disabled} onClick={() => void history(view.root, view.before, view.depth, view.minimumRevision)}><RefreshCw size={15} aria-hidden="true" />Refresh revisions</button></div>
        {!view.page.items.length && <p className="wc-message">No earlier retained revisions.</p>}
        <div className="wce-records wce-history">{view.page.items.map(item => <EvidenceCard key={item.revision} item={item} masked={masked} disabled={disabled} inspect={() => void inspect(item, view.root, view.minimumRevision)} />)}</div>
        <div className="wc-toolbar"><button className="ws-text" disabled={disabled || view.before === null} onClick={() => void history(view.root, null, 0, view.minimumRevision)}>Newest revisions</button><button className="ws-text" disabled={disabled || !view.page.next_before || view.depth >= CREDIT_MAX_PAGES - 1} onClick={() => void history(view.root, view.page.next_before, view.depth + 1, view.minimumRevision)}>Earlier revisions<ArrowRight size={15} aria-hidden="true" /></button></div>{view.page.next_before && view.depth >= CREDIT_MAX_PAGES - 1 && <p className="ws-notice">This view reached its history page limit. Earlier revisions remain saved.</p>}
      </>}
      {view.kind === 'inspect' && <>
        <div className="wc-toolbar"><button className="ws-text" disabled={disabled} onClick={() => void page()}><ArrowLeft size={15} aria-hidden="true" />Back to evidence list</button><button className="ws-text" disabled={disabled} onClick={() => void inspect(view.item, view.root, view.minimumRevision)}><RefreshCw size={15} aria-hidden="true" />Refresh this revision</button></div>
        <EvidenceCard item={view.item} masked={masked} disabled={disabled} detailed history={() => void history(view.root, null, 0, view.minimumRevision)} />
      </>}
    </>}
  </section>
}
