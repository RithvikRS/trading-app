import { useEffect, useRef, useState } from 'react'
import { ArrowLeft, ArrowRight, History, Link2, LoaderCircle, RefreshCw } from 'lucide-react'
import { FinancialRequestError } from './auth'
import type { AuthController } from './auth'
import type { AccountPage } from './accounts'
import { BANK_MAPPING_PAGE_SIZE, MAX_BANK_MAPPING_PAGES, MAX_BANK_MAPPING_REVISION, bankMappingAnchor, bankMappingChange, bankMappingHistory, bankMappingResult, bankSourceAnchor, bankSourceState, eligibleBankTarget, mappingAccounts, mappingSources, sameBankMapping } from './bank-mappings'
import type { BankMappingAnchor, BankMappingHistory, BankMappingScope, BankMappingTransition, MappingCursor, MappingSource, MappingSourcePage, PendingBankMapping } from './bank-mappings'
import './bank-mappings.css'

type Review = { kind: 'review'; scope: BankMappingScope; history: BankMappingHistory; before: number | null; historyPages: number; accounts: AccountPage; cursor: MappingCursor; result?: BankMappingTransition }
type View = { kind: 'closed' } | { kind: 'loading'; message: string } | { kind: 'sources'; page: MappingSourcePage; cursor: MappingCursor } | Review | { kind: 'saving' | 'uncertain'; pending: PendingBankMapping } | { kind: 'saved'; result: BankMappingTransition } | { kind: 'failed'; conflict: boolean }
const first = (): MappingCursor => ({ after: null, previous: [] })
const institutions = { hdfc_statement: 'HDFC', sbi_statement: 'SBI' }
const reasons = { initial: 'Initial link', correction: 'Corrected link', unlinked: 'Unlinked' }
const scopeOf = (value: BankMappingAnchor): BankMappingScope => Object.freeze({ source_id: value.source_id, namespace: value.namespace })
const headOf = (value: BankMappingHistory): BankMappingAnchor => bankMappingAnchor({ ...scopeOf(value), head_revision: value.head_revision, head: value.head })
function HistoricalResult({ value }: { value: BankMappingTransition }) {
  return <aside className="bm-result" aria-label="Historical saved transition"><span className="ws-eyebrow">Saved transition found</span><h4>{reasons[value.reason]} · Revision {value.revision}</h4><p>This saved transition does not prove which request created it, or that the assignment or account status is still current.</p><dl><div><dt>Source</dt><dd>{value.source_id}</dd></div><div><dt>Account at this transition</dt><dd>{value.account_id ?? 'Unlinked'}</dd></div><div><dt>Previous revision</dt><dd>{value.previous_revision ?? 'No previous transition'}</dd></div></dl></aside>
}
function Paging({ cursor, next, count, label, disabled, load }: { cursor: MappingCursor; next: string | null; count: number; label: string; disabled: boolean; load: (cursor: MappingCursor) => void }) {
  const limited = cursor.previous.length >= MAX_BANK_MAPPING_PAGES - 1
  return <><p className="ws-hint" role="status">{label} page {cursor.previous.length + 1} · {count} records read on this page</p><div className="bm-actions"><button className="ws-secondary" disabled={disabled || !cursor.previous.length} onClick={() => load({ after: cursor.previous.at(-1)!, previous: cursor.previous.slice(0, -1) })}><ArrowLeft size={15} aria-hidden="true" />Previous {label.toLowerCase()} page</button><button className="ws-secondary" disabled={disabled || !next || limited} onClick={() => load({ after: next, previous: [...cursor.previous, cursor.after] })}>Next {label.toLowerCase()} page<ArrowRight size={15} aria-hidden="true" /></button></div>{cursor.after && <button className="ws-text" disabled={disabled} onClick={() => load(first())}>First {label.toLowerCase()} page</button>}{next && limited && <p className="ws-notice">This view reached its page limit. More records may be saved.</p>}</>
}
export default function BankSourceAssignments({ auth, busy }: { auth: AuthController; busy: boolean }) {
  const [view, setView] = useState<View>({ kind: 'closed' }), [target, setTarget] = useState(''), [reviewed, setReviewed] = useState(false), [error, setError] = useState('')
  const mounted = useRef(true), generation = useRef(0), guard = useRef(false), owner = useRef<string | undefined>(undefined), opened = useRef(false)
  const heads = useRef(new Map<string, BankMappingAnchor>()), retained = useRef(new Map<string, BankMappingTransition>())
  const heading = useRef<HTMLHeadingElement>(null), entry = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    mounted.current = true
    const screen = auth.snapshot().screen; owner.current = screen.kind === 'workspace' ? screen.session.workspace_context : undefined
    const unsubscribe = auth.subscribe(() => {
      const screen = auth.snapshot().screen
      if (screen.kind !== 'workspace' || screen.session.workspace_context !== owner.current) {
        generation.current++; guard.current = false; owner.current = undefined; heads.current.clear(); retained.current.clear()
        setView({ kind: 'closed' }); setTarget(''); setReviewed(false); setError('')
      }
    })
    return () => { mounted.current = false; generation.current++; guard.current = false; heads.current.clear(); retained.current.clear(); unsubscribe() }
  }, [auth])
  useEffect(() => { if (view.kind !== 'closed') heading.current?.focus(); else if (opened.current) entry.current?.focus(); opened.current = view.kind !== 'closed' }, [view.kind])
  const current = (token: number) => { const screen = auth.snapshot().screen; return mounted.current && generation.current === token && screen.kind === 'workspace' && screen.session.workspace_context === owner.current }
  const begin = () => {
    const state = auth.snapshot()
    if (guard.current || busy || state.busy || state.screen.kind !== 'workspace' || state.screen.session.workspace_context !== owner.current) return undefined
    guard.current = true; setError(''); setTarget(''); setReviewed(false); return ++generation.current
  }
  const end = (token: number) => { if (current(token)) guard.current = false }
  const close = () => { generation.current++; guard.current = false; setTarget(''); setReviewed(false); setError(''); setView({ kind: 'closed' }) }
  const readSources = async (cursor: MappingCursor, token: number) => {
    const page = await auth.finance('/sources/query', { limit: BANK_MAPPING_PAGE_SIZE, after: cursor.after }, value => current(token) ? mappingSources(value, cursor.after, heads.current, retained.current) : undefined)
    if (!current(token) || !page) return undefined
    for (const item of page.items) if (item.namespace === 'hdfc_statement' || item.namespace === 'sbi_statement') heads.current.set(item.id, bankSourceAnchor(item, heads.current.get(item.id)))
    return page
  }
  const readHistory = async (scope: BankMappingScope, before: number | null, token: number) => {
    const anchor = heads.current.get(scope.source_id)
    if (!anchor || anchor.namespace !== scope.namespace) throw new Error('Source review is unavailable.')
    const historical = retained.current.get(scope.source_id), floor = Math.max(anchor.head_revision, historical?.revision ?? 0)
    const history = await auth.finance('/bank-source-mappings/history', { source_id: scope.source_id, limit: BANK_MAPPING_PAGE_SIZE, before }, value => current(token) ? bankMappingHistory(value, anchor, before, floor, historical) : undefined)
    if (!current(token) || !history) return undefined
    heads.current.set(scope.source_id, headOf(history)); return history
  }
  const readAccounts = (history: BankMappingHistory, cursor: MappingCursor, token: number) => auth.finance('/accounts/query', { limit: BANK_MAPPING_PAGE_SIZE, after: cursor.after }, value => current(token) ? mappingAccounts(value, cursor.after, headOf(history)) : undefined)
  const showReview = async (scope: BankMappingScope, token: number, options: { before?: number | null; historyPages?: number; cursor?: MappingCursor; result?: BankMappingTransition; history?: BankMappingHistory } = {}) => {
    const before = options.before ?? null, cursor = options.cursor ?? first()
    const history = options.history ?? await readHistory(scope, before, token)
    if (!current(token) || !history) return
    const accounts = await readAccounts(history, cursor, token)
    if (current(token) && accounts) setView({ kind: 'review', scope, history, before, historyPages: options.historyPages ?? 0, accounts, cursor, result: options.result })
  }
  const directory = async (cursor: MappingCursor = first()) => {
    const token = begin(); if (token === undefined) return
    setView({ kind: 'loading', message: 'Reading saved source identities…' })
    try { const page = await readSources(cursor, token); if (current(token) && page) setView({ kind: 'sources', page, cursor }) }
    catch { if (current(token)) setView({ kind: 'failed', conflict: false }) } finally { end(token) }
  }
  const select = async (source: MappingSource) => {
    const token = begin(); if (token === undefined) return
    setView({ kind: 'loading', message: 'Checking the current assignment and saved accounts…' })
    try { const anchor = bankSourceAnchor(source, heads.current.get(source.id)); heads.current.set(source.id, anchor); await showReview(scopeOf(anchor), token) }
    catch { if (current(token)) setView({ kind: 'failed', conflict: false }) } finally { end(token) }
  }
  const inspect = async (previous: Review, cursor: MappingCursor, before = previous.before, historyPages = previous.historyPages) => {
    const token = begin(); if (token === undefined) return
    setView({ kind: 'loading', message: 'Refreshing assignment evidence…' })
    try { await showReview(previous.scope, token, { cursor, before, historyPages, result: previous.result }) }
    catch { if (current(token)) setView({ kind: 'failed', conflict: false }) } finally { end(token) }
  }
  const save = async (pending: PendingBankMapping, token: number) => {
    setView({ kind: 'saving', pending })
    let result: BankMappingTransition | undefined
    try { result = await auth.finance('/bank-source-mappings/change', pending.command, value => current(token) ? bankMappingResult(value, pending) : undefined) }
    catch (failure) {
      if (current(token)) setView(failure instanceof FinancialRequestError && failure.conflict ? { kind: 'failed', conflict: true } : { kind: 'uncertain', pending })
      return
    }
    if (!current(token) || !result) return
    const older = retained.current.get(result.source_id)
    if (!older || older.revision < result.revision) retained.current.set(result.source_id, result)
    // A historical response raises the existence floor; it never replaces the observed current head.
    setView({ kind: 'loading', message: 'Refreshing current source and account records…' })
    try {
      const page = await readSources(first(), token)
      if (current(token) && page) await showReview(scopeOf(pending.predecessor), token, { result })
    } catch { if (current(token)) setView({ kind: 'saved', result }) }
  }
  const submit = async () => {
    if (view.kind !== 'review' || view.before !== null || !reviewed || !target) return
    const previous = view
    let pending: PendingBankMapping
    try {
      const chosen = target === 'unlink' ? null : previous.accounts.items.find(item => item.id === target)
      if (chosen === undefined) throw new Error('Choose a saved account.')
      const eligible = chosen === null ? null : eligibleBankTarget(chosen, previous.scope)
      if (chosen !== null && eligible === null) throw new Error('Choose a compatible account.')
      pending = bankMappingChange(headOf(previous.history), eligible)
    } catch { setError('Choose a different compatible active account, or unlink an existing assignment.'); return }
    const token = begin(); if (token === undefined) return
    setView({ kind: 'loading', message: 'Checking the assignment before changing it…' })
    try {
      const history = await readHistory(previous.scope, null, token)
      if (!current(token) || !history) return
      if (history.head_revision !== pending.command.expected_revision || !sameBankMapping(history.head, pending.predecessor.head)) { await showReview(previous.scope, token, { history }); return }
      const accounts = await readAccounts(history, previous.cursor, token)
      if (!current(token) || !accounts) return
      if (pending.target) {
        const found = accounts.items.find(item => item.id === pending.target!.id), fresh = found && eligibleBankTarget(found, previous.scope)
        if (!fresh || fresh.revision !== pending.target.revision || fresh.label !== pending.target.label || fresh.currencies.join(',') !== pending.target.currencies.join(',')) {
          setView({ ...previous, history, accounts }); setError('The account directory changed. Review it and choose again.'); return
        }
      }
      await save(pending, token)
    } catch { if (current(token)) setView({ kind: 'failed', conflict: false }) } finally { end(token) }
  }
  const retry = async () => { if (view.kind !== 'uncertain') return; const pending = view.pending, token = begin(); if (token === undefined) return; try { await save(pending, token) } finally { end(token) } }
  const waiting = view.kind === 'loading' || view.kind === 'saving', disabled = busy || waiting
  const eligible = view.kind === 'review' ? view.accounts.items.map(item => eligibleBankTarget(item, view.scope)).filter(item => item !== null) : []
  const currentAccount = view.kind === 'review' ? view.accounts.items.find(item => item.id === view.history.head?.account_id) : undefined
  return <div className="bm-assignments"><div className="bm-entry"><div><Link2 size={19} aria-hidden="true" /><span>Assign an existing bank source to a saved account.</span></div><button ref={entry} className="ws-secondary" disabled={busy || view.kind !== 'closed'} onClick={() => void directory()}>Review bank source assignments</button></div>
    {view.kind !== 'closed' && <section className="bm-panel" aria-labelledby="bank-mappings-heading" aria-busy={waiting}><div className="bm-title"><div><span className="ws-eyebrow">Bank source assignments</span><h3 id="bank-mappings-heading" ref={heading} tabIndex={-1}>{view.kind === 'sources' ? 'Choose a saved bank source.' : view.kind === 'uncertain' ? 'The change is not confirmed.' : view.kind === 'saved' ? 'Saved transition found.' : view.kind === 'review' ? 'Review this source assignment.' : 'Saved source assignments.'}</h3></div><Link2 size={23} aria-hidden="true" /></div>
      {view.kind === 'loading' && <p className="bm-status" role="status"><LoaderCircle className="ws-spin" size={19} aria-hidden="true" />{view.message}</p>}
      {view.kind === 'sources' && <><p className="ws-hint">Choose an existing HDFC or SBI source. This screen does not register sources or make statement imports available.</p><button className="ws-text" disabled={disabled} onClick={() => void directory(view.cursor)}><RefreshCw size={15} aria-hidden="true" />Refresh saved sources</button>{!view.page.items.some(item => item.namespace === 'hdfc_statement' || item.namespace === 'sbi_statement') && <p className="ws-notice">No HDFC or SBI sources on this page. Other pages may contain sources. An empty installation needs a supported intake path to register a source before it can be assigned here.</p>}<ul className="bm-sources" aria-label="Saved bank sources">{view.page.items.filter(item => item.namespace === 'hdfc_statement' || item.namespace === 'sbi_statement').map(source => <li key={source.id}><span className="ws-eyebrow">{institutions[source.namespace as keyof typeof institutions]}</span><p className="bm-identifier">{source.id}</p><p>{bankSourceState(source)}{source.mapping_revision !== null ? ` · Directory revision ${source.mapping_revision}` : ''}</p><button className="ws-secondary" disabled={disabled} aria-label={`Review assignment for source ${source.id}`} onClick={() => void select(source)}>Review assignment<ArrowRight size={15} aria-hidden="true" /></button></li>)}</ul><Paging cursor={view.cursor} next={view.page.next_after} count={view.page.items.length} label="Source" disabled={disabled} load={cursor => void directory(cursor)} /></>}
      {view.kind === 'review' && <><div className="bm-actions"><button className="ws-text" disabled={disabled} onClick={() => void directory()}><ArrowLeft size={15} aria-hidden="true" />Choose another source</button><button className="ws-text" disabled={disabled} onClick={() => void inspect(view, first(), null, 0)}><RefreshCw size={15} aria-hidden="true" />Refresh current assignment</button></div><p className="bm-source-name">{institutions[view.scope.namespace]} · <span>{view.scope.source_id}</span></p>{view.result && <HistoricalResult value={view.result} />}
        <article className="bm-current"><h4>Latest observed assignment</h4><p>{view.history.head === null ? 'Never linked' : view.history.head.account_id === null ? 'Explicitly unlinked' : currentAccount?.state === 'archived' ? 'Linked to archived account' : 'Linked'} · Head revision {view.history.head_revision}</p>{view.history.head?.account_id && <p className="bm-identifier">Account {view.history.head.account_id}</p>}{view.history.head?.account_id && <p className="ws-hint">{currentAccount ? `Account status on the refreshed directory page: ${currentAccount.state === 'archived' ? 'Archived' : 'Active'}.` : 'The target account is not on this directory page. Its current status is not shown here.'}</p>}<p className="ws-hint">A history head is an observation of saved assignment state. It does not prove delivery of an earlier request.</p></article>
        <div className="bm-history"><h4><History size={17} aria-hidden="true" />Saved assignment history</h4>{!view.history.items.length && <p>No transitions in this history window.</p>}<ol aria-label="Assignment transitions">{view.history.items.map(item => <li key={item.revision}><strong>{reasons[item.reason]} · Revision {item.revision}</strong><span>Previous revision {item.previous_revision ?? 'none'}</span><span className="bm-identifier">{item.account_id ? `Account ${item.account_id}` : 'No assigned account'}</span></li>)}</ol><div className="bm-actions"><button className="ws-secondary" disabled={disabled || view.before === null} onClick={() => void inspect(view, view.cursor, null, 0)}>Latest assignment history</button><button className="ws-secondary" disabled={disabled || !view.history.next_before || view.historyPages >= MAX_BANK_MAPPING_PAGES - 1} onClick={() => void inspect(view, view.cursor, view.history.next_before, view.historyPages + 1)}>Earlier assignment history<ArrowRight size={15} aria-hidden="true" /></button></div>{view.history.next_before && view.historyPages >= MAX_BANK_MAPPING_PAGES - 1 && <p className="ws-notice">This view reached its history page limit. Earlier transitions may still be saved.</p>}</div>
        {view.before === null && <><h4 className="bm-choice-title">Choose an assignment change</h4><p className="ws-hint">Only compatible active bank accounts on this page can be selected. Archived targets can be unlinked or replaced. Other pages may contain more accounts.</p>{view.history.head_revision >= MAX_BANK_MAPPING_REVISION ? <p className="ws-notice">This source has reached the supported revision limit. Its history remains available.</p> : <form onSubmit={event => { event.preventDefault(); void submit() }}><fieldset className="bm-targets" disabled={disabled}><legend>New assignment</legend>{eligible.filter(item => item.id !== view.history.head?.account_id).map(item => <label key={item.id}><input type="radio" name="bank-mapping-target" value={item.id} checked={target === item.id} onChange={() => { setTarget(item.id); setReviewed(false); setError('') }} /><span><strong>{item.label}</strong><small>{item.currencies.join(' · ')} native currencies</small><small className="bm-identifier">Account ID {item.id}</small></span></label>)}{view.history.head?.account_id && <label><input type="radio" name="bank-mapping-target" value="unlink" checked={target === 'unlink'} onChange={() => { setTarget('unlink'); setReviewed(false); setError('') }} /><span><strong>Unlink this source</strong><small>Keep the saved historical transitions.</small></span></label>}{!eligible.some(item => item.id !== view.history.head?.account_id) && <p className="ws-hint">No different eligible bank account on this page. This does not establish that none are saved.</p>}</fieldset><label className="bm-confirm"><input type="checkbox" checked={reviewed} disabled={disabled || !target} onChange={event => setReviewed(event.target.checked)} />I reviewed the source, latest history and account directory and intend this change.</label>{error && <p className="ws-notice" role="alert">{error}</p>}<button className="ws-primary" type="submit" disabled={disabled || !reviewed || !target}>{target === 'unlink' ? 'Unlink source' : view.history.head_revision === 0 ? 'Link source to account' : 'Correct source assignment'}<ArrowRight size={15} aria-hidden="true" /></button></form>}<Paging cursor={view.cursor} next={view.accounts.next_after} count={view.accounts.items.length} label="Account" disabled={disabled} load={cursor => void inspect(view, cursor)} /></>}
      </>}
      {(view.kind === 'saving' || view.kind === 'uncertain') && <><p className="bm-status" role="status">{view.kind === 'saving' ? 'Saving the assignment change…' : 'A matching transition may already be saved. Retry the same change, or review saved sources before choosing a new assignment.'}</p><div className="bm-pending"><strong>{institutions[view.pending.predecessor.namespace]} source</strong><span className="bm-identifier">{view.pending.command.source_id}</span><span>From revision {view.pending.command.expected_revision}</span><span>{view.pending.target ? `Assign to ${view.pending.target.label}` : 'Unlink this source'}</span>{view.pending.target && <span className="bm-identifier">Account ID {view.pending.target.id}</span>}</div>{view.kind === 'uncertain' && <div className="bm-actions"><button className="ws-primary" disabled={disabled} onClick={() => void retry()}>Retry the same change</button><button className="ws-secondary" disabled={disabled} onClick={() => void directory()}>Review saved sources</button></div>}</>}
      {view.kind === 'saved' && <><HistoricalResult value={view.result} /><p className="ws-notice">Current source and account records could not be refreshed. Review them before making another change.</p><button className="ws-secondary" disabled={disabled} onClick={() => void directory()}>Review saved sources</button></>}
      {view.kind === 'failed' && <div className="bm-status" role="alert"><div><strong>{view.conflict ? 'The assignment needs a fresh review.' : 'Saved assignments could not be checked.'}</strong><p>Previous source and account details are hidden. Review the source directory and latest history before a new change. A conflict does not prove an older request failed.</p><button className="ws-secondary" disabled={disabled} onClick={() => void directory()}>Review saved sources</button></div></div>}
      <p className="bm-scope">Assignment changes do not move or reinterpret previously saved financial records. Source references, bank credentials and live connections are not collected here.</p><button className="ws-text" disabled={waiting} onClick={close}>Close assignments</button>
    </section>}
  </div>
}
