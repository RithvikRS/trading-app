import { useEffect, useRef, useState } from 'react'
import { ArrowLeft, ArrowRight, CreditCard, History, Link2, RefreshCw } from 'lucide-react'
import type { AuthController, Screen } from './auth'
import { CREDIT_MAX_PAGES, CREDIT_PAGE_SIZE, creditAccountInspection, creditAccounts, creditMappingHistory, creditSources, creditSourceState } from './credit-identities'
import type { CreditAccount, CreditCursor, CreditHistory, CreditMapping, CreditPage, CreditSource } from './credit-identities'
import './credit-workspace.css'

type View =
  | { kind: 'accounts'; page: CreditPage<CreditAccount>; cursor: CreditCursor }
  | { kind: 'account'; account: CreditAccount }
  | { kind: 'sources'; page: CreditPage<CreditSource>; cursor: CreditCursor }
  | { kind: 'history'; source: CreditSource; page: CreditHistory; before: number | null; minimumRevision: number | null }
const firstPage = (): CreditCursor => ({ after: null, previous: [] })
const lifecycle = (state: 'active' | 'archived') => state === 'active' ? 'Active' : 'Archived'
const reason = (entry: CreditMapping) => entry.reason === 'initial' ? 'Initial link' : entry.reason === 'unlinked' ? 'Source unlinked' : 'Link corrected'
function Paging({ cursor, next, count, label, disabled, load }: { cursor: CreditCursor; next: string | null; count: number; label: string; disabled: boolean; load: (cursor: CreditCursor) => void }) {
  const reachedLimit = cursor.previous.length >= CREDIT_MAX_PAGES - 1
  return <><p className="ws-hint" role="status">{label} page {cursor.previous.length + 1} · {count} shown</p><div className="wc-toolbar"><button className="ws-text" disabled={disabled || !cursor.previous.length} onClick={() => load({ after: cursor.previous.at(-1)!, previous: cursor.previous.slice(0, -1) })}><ArrowLeft size={15} aria-hidden="true" />Previous {label.toLowerCase()} page</button><button className="ws-text" disabled={disabled || !next || reachedLimit} onClick={() => load({ after: next, previous: [...cursor.previous, cursor.after] })}>Next {label.toLowerCase()} page<ArrowRight size={15} aria-hidden="true" /></button></div>{cursor.after && <button className="ws-text" disabled={disabled} onClick={() => load(firstPage())}>First {label.toLowerCase()} page</button>}{next && reachedLimit && <p className="ws-notice">This view reached its page limit. More records may be saved.</p>}</>
}
export default function CreditAccountsWorkspace({ auth, busy }: { auth: AuthController; screen: Extract<Screen, { kind: 'workspace' }>; busy: boolean }) {
  const [view, setView] = useState<View>(), [loading, setLoading] = useState(true), [failed, setFailed] = useState(false)
  const started = useRef(false), mounted = useRef(true), generation = useRef(0), heading = useRef<HTMLHeadingElement>(null)
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; generation.current++ } }, [])
  useEffect(() => { heading.current?.focus() }, [view, loading, failed])
  const disabled = busy || loading
  const work = async (read: () => Promise<View | undefined>) => {
    const current = ++generation.current
    setView(undefined); setLoading(true); setFailed(false)
    try { const next = await read(); if (mounted.current && generation.current === current) setView(next) }
    catch { if (mounted.current && generation.current === current) setFailed(true) }
    finally { if (mounted.current && generation.current === current) setLoading(false) }
  }
  const accounts = (cursor = firstPage()) => work(async () => {
    const page = await auth.finance('/credit/accounts/query', { limit: CREDIT_PAGE_SIZE, after: cursor.after }, value => creditAccounts(value, cursor.after))
    return page && { kind: 'accounts', page, cursor }
  })
  const inspect = (selected: string | CreditAccount) => work(async () => {
    const account = await auth.finance('/credit/accounts/inspect', { id: typeof selected === 'string' ? selected : selected.id }, value => creditAccountInspection(value, selected))
    return account && { kind: 'account', account }
  })
  const sources = (cursor = firstPage()) => work(async () => {
    const page = await auth.finance('/credit/sources/query', { limit: CREDIT_PAGE_SIZE, after: cursor.after }, value => creditSources(value, cursor.after))
    return page && { kind: 'sources', page, cursor }
  })
  const history = (source: CreditSource, before: number | null = null, minimumRevision = source.mapping_revision) => work(async () => {
    const page = await auth.finance('/credit/sources/mappings/history', { id: source.id, limit: CREDIT_PAGE_SIZE, before }, value => creditMappingHistory(value, source, before, minimumRevision))
    return page && { kind: 'history', source, page, before, minimumRevision: page.items.length ? Math.max(minimumRevision ?? 0, page.items[0]!.revision) : minimumRevision }
  })
  useEffect(() => {
    if (started.current || busy) return
    let cancelled = false
    queueMicrotask(() => { if (cancelled || started.current || auth.snapshot().busy) return; started.current = true; void accounts() })
    return () => { cancelled = true }
  }, [auth, busy])
  const sourceView = view?.kind === 'sources' || view?.kind === 'history'
  const title = view?.kind === 'history' ? 'Source link history' : view?.kind === 'sources' ? 'Your credit sources' : view?.kind === 'account' ? view.account.label : 'Your credit accounts'
  return <section className="wc-workspace" aria-labelledby="credit-heading" aria-busy={loading}>
    <div className="wc-title"><div><span className="ws-eyebrow">Credit, with context</span><h2 id="credit-heading" ref={heading} tabIndex={-1}>{title}</h2><p>Saved HDFC billing identities and their source links.</p></div><CreditCard size={30} aria-hidden="true" /></div>
    <div className="wc-tabs" role="group" aria-label="Credit identity views"><button disabled={disabled} aria-pressed={!sourceView && !!view} onClick={() => void accounts()}>Billing accounts</button><button disabled={disabled} aria-pressed={sourceView} onClick={() => void sources()}>Source directory</button></div>
    {loading && <p className="wc-message" role="status">Checking saved credit identities…</p>}
    {failed && <div className="wc-message" role="alert"><strong>Credit identities could not be verified.</strong><p>Previous account and source details have been cleared.</p><button className="ws-secondary" disabled={disabled} onClick={() => void accounts()}>Reload credit accounts</button></div>}
    {view?.kind === 'accounts' && <>
      <div className="wc-toolbar"><h3>Saved billing accounts</h3><button className="ws-text" disabled={disabled} onClick={() => void accounts(view.cursor)}><RefreshCw size={15} aria-hidden="true" />Refresh accounts</button></div>
      {!view.page.items.length && <p className="wc-message">No billing accounts on this page. This is not a balance or debt summary.</p>}
      <ul className="wc-list wc-accounts" aria-label="Saved credit billing accounts">{view.page.items.map(account => <li className="wc-card" key={account.id}><div className="wc-card-heading"><span className="wc-card-mark"><CreditCard size={22} aria-hidden="true" /></span><span className="wc-state">{lifecycle(account.state)}</span></div><h3>{account.label}</h3><p>HDFC · INR billing currency</p><button className="ws-secondary" disabled={disabled} aria-label={`Inspect account ${account.label}`} onClick={() => void inspect(account)}>Inspect account<ArrowRight size={15} aria-hidden="true" /></button></li>)}</ul>
      <Paging cursor={view.cursor} next={view.page.next_after} count={view.page.items.length} label="Account" disabled={disabled} load={cursor => void accounts(cursor)} />
    </>}
    {view?.kind === 'account' && <>
      <div className="wc-toolbar"><button className="ws-text" disabled={disabled} onClick={() => void accounts()}><ArrowLeft size={15} aria-hidden="true" />All billing accounts</button><button className="ws-text" disabled={disabled} onClick={() => void inspect(view.account)}><RefreshCw size={15} aria-hidden="true" />Refresh identity</button></div>
      <div className="wc-card"><div className="wc-card-heading"><h3>Billing account identity</h3><span className="wc-state">{lifecycle(view.account.state)}</span></div><dl className="wc-meta"><div><dt>Issuer</dt><dd>HDFC</dd></div><div><dt>Billing currency</dt><dd>INR</dd></div><div><dt>Identity revision</dt><dd>{view.account.revision}</dd></div></dl><details><summary>Saved identity reference</summary><dl className="wc-meta"><div><dt>Account reference</dt><dd>{view.account.id}</dd></div></dl><p className="ws-hint">This is an application reference, not a card number. A billing account may differ from an individual physical card.</p></details></div>
      <p className="wc-note">This view does not show balances, payment status, limits or statements. An archived identity remains available for historical inspection.</p>
      <button className="ws-text" disabled={disabled} onClick={() => void sources()}><Link2 size={15} aria-hidden="true" />Browse all credit sources</button>
    </>}
    {view?.kind === 'sources' && <>
      <div className="wc-toolbar"><h3>Saved sources</h3><button className="ws-text" disabled={disabled} onClick={() => void sources(view.cursor)}><RefreshCw size={15} aria-hidden="true" />Refresh sources</button></div>
      <p className="wc-note">This directory covers all saved credit sources, including unlinked sources and links to other billing accounts. Saving a source does not confirm an imported statement or a live connection.</p>
      {!view.page.items.length && <p className="wc-message">No saved sources on this page. Other pages may contain more.</p>}
      <ul className="wc-list wc-sources" aria-label="Saved credit sources">{view.page.items.map(source => <li className="wc-card" key={source.id}><div className="wc-card-heading"><h3>HDFC statement source</h3><span className="wc-state">{creditSourceState(source)}</span></div><p>{source.mapping_revision === null ? 'No link revision has been saved.' : `Latest saved link revision ${source.mapping_revision}`}</p><details><summary>Source references</summary><dl className="wc-meta"><div><dt>Source reference</dt><dd>{source.id}</dd></div><div><dt>Linked account</dt><dd>{source.account_id ?? 'None'}</dd></div></dl></details><div className="wc-actions"><button className="ws-text" disabled={disabled} aria-label={`Link history for source ${source.id}`} onClick={() => void history(source)}><History size={15} aria-hidden="true" />Link history</button>{source.account_id && <button className="ws-text" disabled={disabled} aria-label={`Inspect linked account for source ${source.id}`} onClick={() => void inspect(source.account_id!)}>Inspect linked account<ArrowRight size={15} aria-hidden="true" /></button>}</div></li>)}</ul>
      <Paging cursor={view.cursor} next={view.page.next_after} count={view.page.items.length} label="Source" disabled={disabled} load={cursor => void sources(cursor)} />
    </>}
    {view?.kind === 'history' && <>
      <div className="wc-toolbar"><button className="ws-text" disabled={disabled} onClick={() => void sources()}><ArrowLeft size={15} aria-hidden="true" />All credit sources</button><button className="ws-text" disabled={disabled} onClick={() => void history(view.source, view.before, view.minimumRevision)}><RefreshCw size={15} aria-hidden="true" />Refresh link history</button></div>
      <p className="wc-note">Saved link decisions, newest first. Target accounts and reasons belong to each revision; active or archived status is observed when this page is read.</p>
      <details><summary>Selected source reference</summary><p className="ws-hint">{view.source.id}</p></details>
      {!view.page.items.length && <p className="wc-message">{view.before === null ? 'This source has no saved link history.' : 'No earlier link revisions.'}</p>}
      <ol className="wc-list wc-history" aria-label="Credit source link revisions">{view.page.items.map(item => <li className="wc-card" key={item.revision}><div className="wc-card-heading"><h3>Revision {item.revision} · {reason(item)}</h3><span className="wc-state">{item.is_latest_revision ? 'Latest retained' : 'Earlier retained'}</span></div><dl className="wc-meta"><div><dt>Preceding revision</dt><dd>{item.previous_revision ?? 'None — first link'}</dd></div><div><dt>Target account</dt><dd>{item.account_id ?? 'None — unlinked'}</dd></div>{item.account_state && <div><dt>Target status at read</dt><dd>{lifecycle(item.account_state)}</dd></div>}</dl>{item.account_id && <button className="ws-text" disabled={disabled} aria-label={`Inspect account from link revision ${item.revision}`} onClick={() => void inspect(item.account_id!)}>Inspect account<ArrowRight size={15} aria-hidden="true" /></button>}</li>)}</ol>
      <div className="wc-toolbar"><button className="ws-text" disabled={disabled || view.before === null} onClick={() => void history(view.source, null, view.minimumRevision)}>Latest link revisions</button><button className="ws-text" disabled={disabled || !view.page.next_before} onClick={() => void history(view.source, view.page.next_before, view.minimumRevision)}>Earlier link revisions<ArrowRight size={15} aria-hidden="true" /></button></div>
    </>}
    {view && <details><summary>About these saved identities</summary><p className="ws-hint">Pages follow application reference order, not statement date. Saved links can be corrected or unlinked; earlier decisions remain inspectable. These views do not establish complete statement coverage, current financial values, physical card membership or provider access.</p></details>}
  </section>
}
