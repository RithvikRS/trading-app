import { useLayoutEffect, useRef } from 'react'
import type { ReactNode } from 'react'
import { AlertTriangle, Check, ChevronDown, Clock3, Database, FileText, FlaskConical, Layers3, Link2, RotateCcw, Search, ShieldCheck } from 'lucide-react'
import { getHoldings } from './data/holdings'
import { canRunSample, getSourceCoverage, isConnectorId, isScenario, outcomeLabels, scenarios, selectSources, sourceDate } from './data/connections'
import type { ConnectionAction, ConnectionControls, ConnectionSimulation, ConnectionState, ConnectorId, SourceCoverage } from './data/connections'

interface Props {
  tab: 'sources' | 'imports'; onTab: (tab: 'sources' | 'imports') => void; catalog: ReactNode; onOpenImport: (id: string) => void
  view: 'populated' | 'partial' | 'empty' | 'loading'; state: ConnectionState; controls: ConnectionControls
  onAction: (action: ConnectionAction) => void; onChange: (controls: ConnectionControls) => void; onReset: () => void
}

function Simulation({ id, state, onAction }: { id: ConnectorId; state: ConnectionSimulation; onAction: Props['onAction'] }) {
  const scenarioSelect = useRef<HTMLSelectElement>(null)
  const runButton = useRef<HTMLButtonElement>(null)
  const outcomeButton = useRef<HTMLButtonElement>(null)
  const nextFocus = useRef<'scenario' | 'run' | 'outcome' | null>(null)
  useLayoutEffect(() => {
    if (nextFocus.current) ({ scenario: scenarioSelect, run: runButton, outcome: outcomeButton })[nextFocus.current].current?.focus()
    nextFocus.current = null
  }, [state])
  function advance(action: ConnectionAction, target: 'scenario' | 'run' | 'outcome') { nextFocus.current = target; onAction(action) }
  const position = getHoldings().find(item => item.accountId === id)!
  const running = state.outcome === 'running'
  const guidance = state.authorization !== 'illustrative' ? 'This example blocks the holdings request. Simulate access renewal before retrying. Previously received evidence remains available.'
    : state.scenario === 'limited' && !state.retryWindow ? 'Holdings request deferred. The supplied retry condition is 20 Oct 2026, 19:05 IST. Advance the example explicitly; there is no live countdown or automatic retry.'
      : running ? 'No network request is running. Advance this step to inspect the supplied result, or cancel the sample attempt.'
        : state.finished ? 'Walkthrough complete. Choose another scenario or reset sample connection states to start again.'
          : state.outcome === 'cancelled' ? 'The sample attempt was cancelled. Retry starts another explicit local step; the prior receipt and financial dates are retained.'
            : state.outcome === 'blocked' ? 'Illustrative access is now available in this scenario. Retry to inspect the supplied outcome; the earlier blocked attempt remains visible.'
              : state.outcome === 'rate-limited' ? 'The supplied retry condition has been simulated. Retry is now available; the earlier deferred attempt and receipt remain visible.'
          : state.outcome === 'failed' ? 'The sample holdings request failed temporarily. The prior receipt and its source dates remain available. A local retry shows the supplied recovery.'
            : state.scenario === 'never' && !state.receipt ? 'This walkthrough has never received data. Existing portfolio fixtures remain independently available; they are not evidence of a connected provider.'
              : state.scenario === 'partial' ? 'The received sample has older holdings and no activity stream. A successful retry retains those gaps and dates.'
                : 'The sample contains a position snapshot and selected activity. A receipt does not establish a complete ledger or current market data.'
  return <section className="connection-simulation" aria-label="Connector simulation">
    <div className="connection-simulation-heading"><div><span className="eyebrow"><FlaskConical size={14} aria-hidden="true" />Local walkthrough</span><h3>Explore a connection outcome</h3><p>Illustrative scenarios only. No provider is connected.</p></div><label className="holding-select">Sample scenario<select ref={scenarioSelect} value={state.scenario} disabled={running} onChange={event => { if (isScenario(event.target.value)) onAction({ type: 'scenario', id, scenario: event.target.value }) }}>{Object.entries(scenarios).map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label></div>
    <dl className="connection-facts">
      <div><dt>Illustrative authorization</dt><dd>{state.authorization === 'illustrative' ? 'Available in this scenario' : state.authorization === 'expired' ? 'Expired in this scenario' : 'Revoked in this scenario'}</dd></div>
      <div><dt>Latest attempt outcome</dt><dd>{outcomeLabels[state.outcome]}</dd></div>
      <div><dt>Last simulated attempt</dt><dd>{state.attempt ?? 'Never attempted'}</dd></div>
      <div><dt>Last simulated successful receipt</dt><dd>{state.receipt ?? 'Never received'}</dd></div>
    </dl>
    <div className={`connection-guidance ${state.outcome === 'received' ? '' : 'attention'}`}><Clock3 size={18} aria-hidden="true" /><p>{guidance}</p></div>
    <div className="connection-actions">
      {state.authorization !== 'illustrative' && <button className="outlined-button" onClick={() => advance({ type: 'renew', id }, 'run')}>Simulate access renewal</button>}
      {state.scenario === 'limited' && !state.retryWindow && <button className="outlined-button" onClick={() => advance({ type: 'window', id }, 'run')}>Simulate retry window</button>}
      <button ref={runButton} className="primary-button" disabled={!canRunSample(state)} onClick={() => advance({ type: 'run', id }, 'outcome')}>{['available', 'never', 'partial'].includes(state.scenario) ? 'Run sample refresh' : 'Retry sample attempt'}</button>
      {running && <><button ref={outcomeButton} className="outlined-button" onClick={() => advance({ type: 'finish', id }, 'scenario')}>Show sample outcome</button><button className="text-button" onClick={() => advance({ type: 'cancel', id }, 'run')}>Cancel sample attempt</button></>}
    </div>
    <div className="connection-receipt"><h4>Walkthrough receipt evidence</h4>{state.receipt ? <><p>Separate example evidence; it does not replace the financial coverage above.</p><dl className="connection-facts">
      <div><dt>Receipt holdings as of</dt><dd>{state.scenario === 'partial' ? '17 Oct 2026, 09:00 IST' : sourceDate(position.holdingsDate)}</dd></div>
      <div><dt>Receipt quotes as of</dt><dd>{sourceDate(position.quote!.date)}</dd></div>
      <div><dt>Receipt activity coverage</dt><dd>{state.scenario === 'partial' ? 'Missing stream · No activity received' : 'Selected examples · No full period'}</dd></div>
      <div><dt>Receipt statement period</dt><dd>Not supplied</dd></div>
    </dl></> : <p>No receipt evidence exists in this scenario. The financial coverage above describes the bundled portfolio, independently.</p>}</div>
    <details className="connection-history"><summary>Sample attempt history ({state.history.length})</summary><p>Fixed fixture timestamps; at most three retained outcomes. This is not a provider audit log or proof of access.</p>{state.history.length ? <ol>{state.history.map((attempt, index) => <li key={`${index}-${attempt.outcome}`}><span>{attempt.at}</span><strong>{outcomeLabels[attempt.outcome]}</strong></li>)}</ol> : <p>No attempt has completed.</p>}</details>
  </section>
}

function SourceDetail({ source, state, onAction, onClose, onOpenImport }: { source: SourceCoverage; state: ConnectionState; onAction: Props['onAction']; onClose: () => void; onOpenImport: Props['onOpenImport'] }) {
  return <div id={`source-detail-${source.id}`} className="connection-detail" role="region" aria-label={`${source.name} source details`}>
    <div className="connection-boundary"><ShieldCheck size={18} aria-hidden="true" /><div><strong>Bundled sample · No provider connected</strong><p>{source.mode === 'statement' ? 'Statement example only. No connector authorization, credentials, or refresh attempt exists for this source.' : 'Connector scenarios below are simulations. Actual automatic access and provider permission scopes are unverified.'} Real permissions are not established by this interface.</p></div></div>
    <dl className="connection-facts source-identity"><div><dt>Source group</dt><dd>{source.name}</dd></div><div><dt>Account</dt><dd>{source.account} · Sample owner</dd></div><div><dt>Financial snapshot as of</dt><dd>{source.asOf}</dd></div><div><dt>Statement coverage</dt><dd>{source.period}</dd></div></dl>
    <h3>Financial source coverage</h3><p className="connection-caption">Dates come from the existing portfolio fixtures. Each stream keeps its own evidence and gaps.</p>
    <ul className="connection-streams">{source.streams.map(stream => <li key={stream.name}><div><strong>{stream.name}</strong><span>{stream.status}</span></div><div><strong>{stream.date}</strong><p>{stream.note}</p></div></li>)}</ul>
    {isConnectorId(source.id) ? <Simulation id={source.id} state={state.sources[source.id]} onAction={onAction} /> : <div className="connection-statement-note"><FileText size={22} aria-hidden="true" /><div><h3>Statement walkthrough</h3><p>{source.bank ? 'Inspect a bundled bank sample and its incoming rows. No files are selected or imported.' : 'Investment import previews are planned. Inspect the available source dates and gaps above.'} Actual provider export formats remain unverified.</p>{source.bank && <a id={`source-import-${source.id}`} className="text-button" href={`#/connections/imports/${source.id === 'hdfc' ? 'i01' : 'i07'}`} onClick={event => { if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return; event.preventDefault(); onOpenImport(source.id === 'hdfc' ? 'i01' : 'i07') }}>Inspect bank sample</a>}</div></div>}
    <button className="text-button connection-close" onClick={onClose}>Close source details</button>
  </div>
}

export default function Connections({ view, state, controls, onAction, onChange, onReset, tab, onTab, catalog, onOpenImport }: Props) {
  const sources = getSourceCoverage(view === 'partial')
  const selected = selectSources(sources, controls)
  return <div className="connections-workspace">
    <div className="page-heading"><div><span className="eyebrow">A clear line to your sources <span className="mobile-demo">· Sample data</span></span><h1 id="page-title" tabIndex={-1}>{tab === 'imports' ? 'Review what comes in' : 'Know what’s behind the numbers'}<span>.</span></h1><p>{tab === 'imports' ? 'Inspect a statement’s evidence before it would reach your records.' : 'See what each source covers, how old it is, and what needs a closer look.'}</p></div><span className="connection-mode"><ShieldCheck size={16} aria-hidden="true" />No provider connected</span></div>
    <div className="budget-views connection-views" aria-label="Connection views"><button aria-pressed={tab === 'sources'} onClick={() => onTab('sources')}>Sources</button><button aria-pressed={tab === 'imports'} onClick={() => onTab('imports')}>Sample imports</button></div>
    {tab === 'imports' ? catalog : view === 'loading' ? <section aria-busy="true" aria-label="Loading sample sources" className="holdings-loading"><span className="sr-only" role="status">Loading sample sources</span><div className="skeleton-panel"><div className="skeleton number" />{[0, 1, 2].map(row => <div key={row} className="skeleton holding-skeleton-row" />)}</div></section>
      : view === 'empty' ? <section className="empty-state"><Database size={36} aria-hidden="true" /><h2>No sample sources loaded.</h2><p>Explore fictional account coverage and local connection scenarios.</p><button className="primary-button" onClick={onReset}>Explore sample sources</button></section>
        : <>
          <section className="connection-summary" aria-label="Source summary"><div><span className="connection-summary-icon"><Layers3 size={23} aria-hidden="true" /></span><div><span>Bundled sample sources</span><strong>06 <small>across your workspace</small></strong></div></div><div><span>Walkthroughs</span><strong>02 <small>connector simulations</small></strong><p>04 statement examples</p></div><div><span>Financial coverage</span><strong>{sources.some(source => source.attention) ? '3 sources need attention' : 'Snapshot dates vary'}</strong><p>{view === 'partial' ? 'Missing NAV · Stale holdings · Incomplete activity' : 'Bank activity through 20 Oct, 10:00 IST'}</p></div></section>
          <div className="connection-intro"><FlaskConical size={17} aria-hidden="true" /><p>All records are fictional. Walkthrough actions change local statuses only; holdings, balances, budgets, and review decisions stay as they are.</p></div>
          <section className="panel connection-sources" aria-labelledby="sources-title">
            <div className="connection-section-heading"><div><span className="eyebrow">Coverage before confidence</span><h2 id="sources-title" tabIndex={-1}>Your sources</h2><p>Open a source to inspect its streams and freshness.</p></div><button className="text-button" onClick={() => onAction({ type: 'reset' })}><RotateCcw size={14} aria-hidden="true" />Reset sample connection states</button></div>
            <div className="connection-filters"><label className="connection-search"><Search size={17} aria-hidden="true" /><span className="sr-only">Search sources</span><input type="search" value={controls.query} maxLength={80} placeholder="Search sources…" onChange={event => onChange({ ...controls, query: event.target.value.slice(0, 80) })} /></label><label className="holding-select">Source type<select value={controls.filter} onChange={event => { const filter = event.target.value; if (filter === 'all' || filter === 'bank' || filter === 'investment') onChange({ ...controls, filter }) }}><option value="all">All sources</option><option value="investment">Investment accounts</option><option value="bank">Bank statements</option></select></label><span>{selected.length} of {sources.length} sources</span></div>
            <p className="connection-announcement" role="status">{state.message}</p>
            <ul className="connection-source-list">{selected.map(source => {
              const open = source.id === controls.selected
              return <li key={source.id} className={open ? 'expanded' : ''}><button id={`source-${source.id}`} className="connection-source-toggle" aria-expanded={open} aria-controls={`source-detail-${source.id}`} onClick={() => onChange({ ...controls, selected: open ? null : source.id })}>
                <span className="connection-source-name"><span className="connection-source-icon">{source.bank ? <FileText size={20} aria-hidden="true" /> : <Link2 size={20} aria-hidden="true" />}</span><span><strong>{source.name}</strong><small>{source.account}</small></span></span>
                <span className="connection-source-coverage"><span className={source.attention ? 'connection-attention' : ''}>{source.attention ? <AlertTriangle size={13} aria-hidden="true" /> : <Check size={13} aria-hidden="true" />}{source.summary}</span><small>{source.asOf}</small></span>
                <span className="connection-source-kind">{source.mode === 'connector' ? 'Connector simulation' : 'Statement example'}<ChevronDown size={17} className={open ? 'rotated' : ''} aria-hidden="true" /></span>
              </button>{open && <SourceDetail onOpenImport={onOpenImport} source={source} state={state} onAction={onAction} onClose={() => { onChange({ ...controls, selected: null }); document.getElementById(`source-${source.id}`)?.focus() }} />}</li>
            })}</ul>
            {!selected.length && <div className="connection-no-results"><Search size={23} aria-hidden="true" /><h3>No sources match.</h3><p>Try a different source name or account type.</p><button className="outlined-button" onClick={() => onChange({ ...controls, query: '', filter: 'all' })}>Clear source filters</button></div>}
            <div className="connection-local-note"><ShieldCheck size={15} aria-hidden="true" /><p>Scenarios and selections stay in memory until reload. Only theme, display currency, and amount visibility are saved.</p></div>
          </section>
        </>}
  </div>
}
