import { useContext, useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import type { KeyboardEvent, ReactNode } from 'react'
import {
  ArrowDownLeft, ArrowDownUp, ArrowRight, ArrowUpRight, BarChart3, Check, ChevronDown, ChevronRight,
  CircleHelp, Clock3, Eye, EyeOff, FlaskConical, Globe2, LayoutDashboard, Link2,
  Menu, Moon, PieChart, Plus, RefreshCw, ShieldCheck, SlidersHorizontal, Sun, Wallet, X,
  AlertTriangle, Landmark, Activity as ActivityIcon,
} from 'lucide-react'
import {
  accounts, getActivity, assetClasses, AS_OF, axisLabel, FX_DATE, formatMoney, getAccountValue,
  getPositions, getSummary, history, shortDate, sum,
} from './data/portfolio'
import type { Account, Currency, DemoState, Position } from './data/portfolio'
import { readPreferences, savePreferences } from './preferences'
import { Amount, DisplayContext, ReportingAmount } from './display'
import Investments from './Investments'
import HoldingDetail from './HoldingDetail'
import Banking from './Banking'
import Budgets from './Budgets'
import { changeBudgets, createBudgetState } from './data/budgets'
import type { BankCategory } from './data/banking'
import { initialCashControls } from './data/cashFlow'
import { changeRecurring, createRecurringState, initialRecurringControls } from './data/recurring'
import { defaultBankingControls, getBankTransactions } from './data/banking'
import { changeTransfers, createTransferState, initialTransferControls } from './data/transfers'
import type { TransferAction, TransferState } from './data/transfers'
import { initialCategoryControls } from './data/categories'
import { defaultControls } from './data/holdings'
import { useScreen } from './routes'
import type { Screen } from './routes'

const navigation = [
  { label: 'Overview', icon: LayoutDashboard }, { label: 'Investments', icon: BarChart3 },
  { label: 'Banking', icon: Landmark }, { label: 'Budgets', icon: PieChart },
  { label: 'Activity', icon: ActivityIcon }, { label: 'Connections', icon: Link2 },
]

function Brand() {
  return <div className="brand"><span className="brand-mark" aria-hidden="true"><BarChart3 size={22} strokeWidth={2.4} /></span><span>Portfolio<span className="brand-dot">.</span></span></div>
}

type Navigate = ReturnType<typeof useScreen>['navigate']
function Navigation({ screen, navigate, onNavigate }: { screen: Screen; navigate: Navigate; onNavigate?: () => void }) {
  return <nav aria-label="Main navigation" className="navigation">
    <p className="nav-label">Workspace</p>
    {navigation.map(({ label, icon: Icon }, index) => <div key={label}>
      {index === 4 && <p className="nav-label second-label">Manage</p>}
      {index < 4
        ? <a href={`#/${label.toLowerCase()}`} aria-current={screen === label.toLowerCase() ? 'page' : undefined} className={`nav-item ${screen === label.toLowerCase() ? 'active' : ''}`} onClick={event => { if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return; event.preventDefault(); navigate(label === 'Overview' ? 'overview' : label === 'Investments' ? 'investments' : label === 'Banking' ? 'banking' : 'budgets'); onNavigate?.() }}><Icon size={19} aria-hidden="true" />{label}{screen === label.toLowerCase() && <span className="active-dot" />}</a>
        : <span className="nav-item planned" aria-label={`${label}, planned`}><Icon size={19} aria-hidden="true" />{label}<span className="soon">Soon</span></span>}
    </div>)}
  </nav>
}

function Sidebar({ screen, navigate }: { screen: Screen; navigate: Navigate }) {
  return <aside className="sidebar"><Brand /><Navigation screen={screen} navigate={navigate} />
    <div className="sidebar-note"><div className="note-icon"><ShieldCheck size={20} aria-hidden="true" /></div><strong>A private perspective.</strong><p>Your financial picture,<br />all in one place.</p><span className="local-label"><span className="status-dot" />Local demo</span></div>
    <div className="sidebar-bottom"><span className="avatar">P</span><div><strong>Personal workspace</strong><span>Sample portfolio</span></div></div>
  </aside>
}

function Panel({ title, subtitle, children, action, className = '' }: { title: string; subtitle?: string; children: ReactNode; action?: ReactNode; className?: string }) {
  const heading = useId()
  return <section className={`panel ${className}`} aria-labelledby={heading}><div className="panel-heading"><div><h2 id={heading}>{title}</h2>{subtitle && <p>{subtitle}</p>}</div>{action}</div>{children}</section>
}

function ValueChart({ partial }: { partial: boolean }) {
  const { hidden, currency } = useContext(DisplayContext)
  const [range, setRange] = useState('6M')
  const [selected, setSelected] = useState<number | null>(null)
  const [tableOpen, setTableOpen] = useState(false)
  const tableId = useId()
  const series = history.slice(range === '1M' ? -5 : range === '3M' ? -14 : 0)
  const point = series[selected ?? series.length - 1]!
  const values = series.map(item => Number(item.value.minor))
  const min = Math.floor(Math.min(...values) / 10_000_000) * 10_000_000 - 4_000_000
  const max = Math.ceil(Math.max(...values) / 10_000_000) * 10_000_000 + 4_000_000
  const x = (index: number) => 20 + index / (series.length - 1) * 580
  const y = (minor: number) => 22 + (max - minor) / (max - min) * 160
  const line = values.map((value, index) => `${index === 0 ? 'M' : 'L'} ${x(index)} ${y(value)}`).join(' ')
  const highlightIndex = selected ?? series.length - 1
  const lineId = useId().replaceAll(':', '')
  const unavailable = hidden || partial

  function chooseRange(value: string) { setRange(value); setSelected(null) }

  return <Panel title="Asset value over time" subtitle="The bigger picture, across your accounts" className="history-panel" action={
    <div className="segmented" role="group" aria-label="Chart period">{['1M', '3M', '6M'].map(value => <button key={value} aria-pressed={range === value} onClick={() => chooseRange(value)}>{value}</button>)}</div>
  }>
    {unavailable ? <div className="chart-private">{hidden ? <EyeOff size={27} aria-hidden="true" /> : <Clock3 size={27} aria-hidden="true" />}<strong>{hidden ? 'A little more privacy.' : 'A complete picture takes complete data.'}</strong><p>{hidden ? 'Show amounts to explore your value history.' : 'History is paused while one holding is unpriced.'}</p></div>
      : <>
        <div className="chart-readout"><span><span className="status-dot" />{shortDate(point.date)} 2026</span><strong><Amount value={point.value} /></strong><span className="chart-readout-label">Tracked assets</span></div>
        <div className="chart-container">
          <div className="chart-axis" aria-hidden="true">{[max, (max + min) / 2, min].map(value => <span key={value}>{axisLabel({ minor: BigInt(Math.round(value)), currency: 'INR' }, currency)}</span>)}</div>
          <svg className="value-chart" viewBox="0 0 620 205" preserveAspectRatio="none" role="img" aria-label={`${range} tracked asset value history. Use the date slider or data table for individual values.`}
            onPointerMove={event => { const bounds = event.currentTarget.getBoundingClientRect(); setSelected(Math.max(0, Math.min(series.length - 1, Math.round(((event.clientX - bounds.left) / bounds.width * 620 - 20) / 580 * (series.length - 1))))) }} onPointerLeave={() => setSelected(null)}>
            <defs><linearGradient id={lineId} x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="var(--accent)" stopOpacity="0.20" /><stop offset="100%" stopColor="var(--accent)" stopOpacity="0.01" /></linearGradient></defs>
            {[22, 102, 182].map(value => <line key={value} x1="20" y1={value} x2="600" y2={value} className="chart-grid" />)}
            <path d={`${line} L 600 192 L 20 192 Z`} fill={`url(#${lineId})`} />
            <path d={line} className="chart-line" />
            <line x1={x(highlightIndex)} x2={x(highlightIndex)} y1="20" y2="192" className="chart-guide" />
            <circle cx={x(highlightIndex)} cy={y(Number(point.value.minor))} r="5" className="chart-point" />
          </svg>
        </div>
        <div className="chart-dates" aria-hidden="true">{[0, Math.floor((series.length - 1) / 2), series.length - 1].map(index => <span key={index}>{shortDate(series[index]!.date)}</span>)}</div>
        <div className="chart-slider"><label htmlFor={`${tableId}-slider`}>Explore dates</label><input id={`${tableId}-slider`} type="range" min="0" max={series.length - 1} value={highlightIndex} aria-valuetext={`${shortDate(point.date)} 2026, ${formatMoney(point.value, currency)}`} onChange={event => setSelected(Number(event.target.value))} /><button className="text-button" aria-expanded={tableOpen} aria-controls={tableId} onClick={() => setTableOpen(!tableOpen)}>{tableOpen ? 'Hide data' : 'View data'}<ChevronDown size={14} aria-hidden="true" /></button></div>
      </>}
    <div id={tableId} hidden={!tableOpen || unavailable} className="chart-table"><table><caption>Sample asset values · {range} · dated demo FX</caption><thead><tr><th scope="col">Date</th><th scope="col">Tracked assets ({currency})</th></tr></thead><tbody>{series.map(item => <tr key={item.date}><th scope="row">{shortDate(item.date)} 2026</th><td><Amount value={item.value} /></td></tr>)}</tbody></table></div>
    <p className="chart-footnote"><CircleHelp size={13} aria-hidden="true" />Includes deposits, withdrawals and FX changes. This is not investment return.</p>
  </Panel>
}

function Allocation({ positions }: { positions: Position[] }) {
  const { hidden } = useContext(DisplayContext)
  const summary = getSummary(positions)
  const allocation = assetClasses.map(category => {
    const total = sum(positions.filter(item => item.category === category.id).flatMap(item => item.value ? [item.value] : []))
    return { ...category, total, percentage: Number(total.minor) / Number(summary.total.minor) * 100 }
  })
  let cursor = 0
  const segments = allocation.map(item => { const start = cursor; cursor += item.percentage; return { ...item, start, end: cursor } })
  const fill = segments.map(item => `var(--allocation-${item.id}) ${item.start}% ${item.end}%`).join(', ')
  return <Panel title="Your asset mix" subtitle={summary.missing ? 'Allocation of valued assets only' : 'A view of where you stand'} className="allocation-panel">
    <div className="allocation-visual" aria-hidden="true"><div className="allocation-ring" style={{ background: `conic-gradient(${fill})` }}>
      <svg className="allocation-separators" viewBox="0 0 100 100" focusable="false">{segments.map(item => <line key={item.id} x1="50" y1="0" x2="50" y2="50" transform={`rotate(${item.start * 3.6} 50 50)`} vectorEffect="non-scaling-stroke" />)}</svg>
      <div><span>{hidden ? '•••' : '4'}</span><small>asset classes</small></div>
    </div></div>
    <ul className="allocation-list">{allocation.map(item => <li key={item.id}><span className={`allocation-dot ${item.id}`} aria-hidden="true" /><div><span>{item.label}</span><small><Amount value={item.total} /></small></div><strong>{item.percentage.toFixed(1)}<span>%</span></strong></li>)}</ul>
  </Panel>
}

function AccountRow({ account, positions, partial }: { account: Account; positions: Position[]; partial: boolean }) {
  const value = getAccountValue(positions, account.id)
  const missing = value === null
  const stale = partial && account.id === 'ubs'
  const [open, setOpen] = useState(false)
  const detailId = useId()
  const rows = positions.filter(item => item.accountId === account.id)
  return <li className={`account-item ${open ? 'expanded' : ''}`}>
    <button className="account-row" aria-expanded={open} aria-controls={detailId} onClick={() => setOpen(!open)}>
      <span className={`institution-mark ${account.color}`} aria-hidden="true">{account.monogram}</span>
      <span className="account-name"><strong>{account.name}</strong><span>{account.description}</span></span>
      <span className={`account-status ${missing || stale ? 'warning-text' : ''}`}><span className={`status-dot ${missing || stale ? 'warning' : ''}`} />{missing ? 'Price missing' : stale ? 'Holdings stale' : account.id === 'advisor' ? 'Statement · 18 Oct' : 'Updated · 20 Oct'}</span>
      <span className="account-amount"><Amount value={value} /><span>{missing ? 'Not in total' : account.kind === 'bank' ? 'Available cash' : 'Holdings + cash'}</span></span>
      <ChevronRight size={17} className={open ? 'rotated' : ''} aria-hidden="true" />
    </button>
    <div id={detailId} hidden={!open} className="account-detail">
      <dl><div><dt>{account.kind === 'bank' ? 'Balance snapshot' : 'Holdings snapshot'}</dt><dd>{stale ? '17 Oct 2026, 09:00 IST · stale' : account.holdingsDate}</dd></div>{account.priceDate && <div><dt>Price snapshot</dt><dd>{missing ? 'Unavailable for 20 Oct 2026' : account.priceDate}</dd></div>}</dl>
      <ul>{rows.map(item => <li key={item.id}><span>{item.label}</span><strong><ReportingAmount value={item.value} /></strong></li>)}</ul>
      <p>Fictional snapshot. No live account is connected.{missing && ' This holding is excluded from valued assets until a price is available.'}</p>
    </div>
  </li>
}

function AccountsPanel({ positions, partial }: { positions: Position[]; partial: boolean }) {
  return <Panel title="Your accounts" subtitle="Across markets. In one place." className="accounts-panel" action={<span className="quiet-badge">6 accounts</span>}>
    <ul className="accounts-list">{accounts.map(account => <AccountRow key={account.id} account={account} positions={positions} partial={partial} />)}</ul>
    <div className="panel-footer"><ShieldCheck size={14} aria-hidden="true" /><span>Sample snapshots · Select an account for source dates</span></div>
  </Panel>
}

function RecentActivity({ partial, review }: { partial: boolean; review: TransferState }) {
  const icons = { purchase: Plus, dividend: ArrowDownLeft, transfer: ArrowDownUp, spending: ArrowUpRight, unresolved: CircleHelp }
  const labels = { purchase: 'Investment', dividend: 'Income', transfer: 'Internal transfer', spending: 'Spending', unresolved: 'Unreviewed movement' }
  return <Panel title="Recent activity" subtitle="The small moves behind the big picture" className="activity-panel" action={<span className="quiet-badge">Sample</span>}>
    <ul className="activity-list">{getActivity(partial, review).map(item => { const Icon = icons[item.kind]; return <li key={item.id}>
      <span className={`activity-icon ${item.kind}`}><Icon size={17} aria-hidden="true" /></span>
      <div className="activity-copy"><strong>{item.title}</strong><span>{item.detail}</span><small>{shortDate(item.date)} · {labels[item.kind]}</small></div>
      <div className={`activity-value ${item.kind === 'dividend' ? 'positive' : ''}`}><ReportingAmount value={item.value} /></div>
    </li> })}</ul>
    <p className="panel-footer"><ArrowDownUp size={14} aria-hidden="true" /><span>Internal transfers are excluded from income and spending.</span></p>
  </Panel>
}

function Summary({ positions }: { positions: Position[] }) {
  const summary = getSummary(positions)
  return <section className="summary-grid" aria-label="Asset summary">
    <div className="summary-primary"><div className="summary-label"><span>{summary.missing ? 'Valued assets' : 'Tracked assets'}</span><span className="summary-icon"><Wallet size={19} aria-hidden="true" /></span></div><p className="hero-amount"><Amount value={summary.total} /></p><p className="summary-caption"><span className={`status-dot ${summary.missing ? 'warning' : ''}`} />{summary.missing ? 'Excludes 1 unpriced holding' : 'Your investments and cash, together'}</p></div>
    <div className="summary-secondary"><div className="summary-label"><span>Invested assets</span><BarChart3 size={18} aria-hidden="true" /></div><p className="metric-amount"><Amount value={summary.invested} /></p><p className="summary-caption">{summary.missing ? 'Known values only' : 'Indian & US markets · Mutual funds'}</p></div>
    <div className="summary-secondary"><div className="summary-label"><span>Cash balance</span><Landmark size={18} aria-hidden="true" /></div><p className="metric-amount"><Amount value={summary.cash} /></p><p className="summary-caption">Bank accounts & uninvested broker cash</p></div>
  </section>
}

function EmptyState({ reset }: { reset: () => void }) {
  return <section className="empty-state" aria-labelledby="empty-heading"><div className="empty-art" aria-hidden="true"><div /><Wallet size={39} /><span><Plus size={14} /></span></div><span className="eyebrow">A fresh perspective</span><h2 id="empty-heading">Your financial picture starts here.</h2><p>No sample accounts are loaded in this view.<br />Explore the demo to see investments and cash come together.</p><button className="primary-button" onClick={reset}>Explore sample portfolio<ArrowRight size={16} aria-hidden="true" /></button><small>Fictional data. No accounts or sign-in needed.</small></section>
}

function LoadingState() {
  return <section aria-label="Loading sample portfolio" aria-busy="true" className="loading-state"><span className="sr-only" role="status">Loading sample portfolio</span><div className="summary-grid">{[1, 2, 3].map(item => <div className="skeleton-card" key={item}><div className="skeleton short" /><div className="skeleton number" /><div className="skeleton" /></div>)}</div><div className="charts-grid"><div className="skeleton-panel"><div className="skeleton short" /><div className="skeleton chart" /></div><div className="skeleton-panel"><div className="skeleton short" /><div className="skeleton chart" /></div></div></section>
}

export default function App() {
  const { screen, route, transactionOrigin, navigate, openHolding, openTransaction } = useScreen()
  const navScreen = screen === 'holding' ? 'investments' : screen === 'transaction' ? transactionOrigin : screen
  const screenLabel = screen === 'holding' ? 'Holding details' : screen === 'transaction' ? 'Transaction details' : screen === 'banking' ? 'Banking' : screen === 'budgets' ? 'Budgets' : screen === 'investments' ? 'Investments' : screen === 'overview' ? 'Overview' : 'Unavailable'
  const [budgetTab, setBudgetTab] = useState<'monthly' | 'cash' | 'recurring'>('monthly')
  const [recurringState, setRecurringState] = useState(createRecurringState)
  const [recurringControls, setRecurringControls] = useState(initialRecurringControls)
  const [cashControls, setCashControls] = useState(initialCashControls)
  const [budgetState, setBudgetState] = useState(() => createBudgetState())
  const [budgetExpanded, setBudgetExpanded] = useState<BankCategory | null>(null)
  const [bankingControls, setBankingControls] = useState(defaultBankingControls)
  const [transferState, setTransferState] = useState(() => createTransferState())
  const [transferControls, setTransferControls] = useState(initialTransferControls)
  const [categoryControls, setCategoryControls] = useState(initialCategoryControls)
  const [bankingFiltersOpen, setBankingFiltersOpen] = useState(false)
  const [holdingsControls, setHoldingsControls] = useState(defaultControls)
  const [holdingsFiltersOpen, setHoldingsFiltersOpen] = useState(false)
  const [preferences, setPreferences] = useState(readPreferences)
  const [demoState, setDemoState] = useState<DemoState>('populated')
  const [lastGoodState, setLastGoodState] = useState<'populated' | 'partial' | 'empty'>('populated')
  const [retrying, setRetrying] = useState(false)
  const [attentionOpen, setAttentionOpen] = useState(false)
  const retryTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const drawer = useRef<HTMLDialogElement>(null)
  const drawerNavigating = useRef(false)
  const menuButton = useRef<HTMLButtonElement>(null)
  const attentionId = useId()
  const view = demoState === 'error' ? lastGoodState : demoState
  const partial = view === 'partial'
  const positions = getPositions(partial)

  useLayoutEffect(() => { document.documentElement.dataset.theme = preferences.theme; savePreferences(preferences) }, [preferences])
  useEffect(() => { document.title = `Portfolio · ${screenLabel}` }, [screenLabel])
  useEffect(() => () => { if (retryTimer.current) clearTimeout(retryTimer.current) }, [])

  function changeState(value: DemoState) {
    if (retryTimer.current) clearTimeout(retryTimer.current)
    setRetrying(false)
    if (value === 'populated' || value === 'partial' || value === 'empty') setLastGoodState(value)
    if (value === 'empty') { setRecurringState(createRecurringState()); setRecurringControls(initialRecurringControls); setCashControls(initialCashControls); setBudgetState(createBudgetState(false)); setBudgetExpanded(null) }
    else if ((value === 'populated' || value === 'partial') && lastGoodState === 'empty') setBudgetState(createBudgetState())
    if (value === 'empty') { setTransferState(createTransferState(false)); setTransferControls(current => ({ ...current, selected: null })) }
    else if ((value === 'populated' || value === 'partial') && lastGoodState === 'empty') setTransferState(createTransferState())
    if (value === 'partial' || value === 'loading') setTransferControls(current => ({ ...current, selected: null }))
    if (value !== 'error') setCategoryControls(current => ({ ...current, ids: [], preview: null }))
    setDemoState(value)
  }
  function reviewTransfer(action: TransferAction) {
    const records = view === 'empty' || view === 'loading' ? [] : getBankTransactions(partial, null)
    setTransferState(current => changeTransfers(current, action, records))
    setTransferControls(current => ({ ...current, selected: null }))
    setCategoryControls(current => ({ ...current, ids: [], preview: null }))
  }
  function retry() {
    setRetrying(true)
    retryTimer.current = setTimeout(() => { setDemoState(lastGoodState); setRetrying(false) }, 650)
  }
  function closeDrawer() { drawerNavigating.current = false; drawer.current?.close(); menuButton.current?.focus() }
  function navigateFromDrawer() { drawerNavigating.current = true; drawer.current?.close() }
  function finishDrawerClose() {
    if (drawerNavigating.current) {
      if (!/^(holding|transaction|transfer|category|budget|cash|recurring)-link-/.test(document.activeElement?.id ?? '')) document.getElementById('page-title')?.focus({ preventScroll: true })
    }
    else menuButton.current?.focus()
    drawerNavigating.current = false
  }
  function containDrawerFocus(event: KeyboardEvent<HTMLDialogElement>) {
    if (event.key !== 'Tab') return
    const controls = drawer.current?.querySelectorAll<HTMLElement>('button, a[href]')
    const first = controls?.[0]
    const last = controls?.[controls.length - 1]
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
  }

  return <DisplayContext.Provider value={preferences}>
    <a href="#main-content" className="skip-link" onClick={event => { event.preventDefault(); document.getElementById('main-content')?.focus() }}>Skip to {screenLabel.toLowerCase()}</a>
    <div className="app-layout"><Sidebar screen={navScreen} navigate={navigate} />
      <div className="main-shell">
        <header className="topbar">
          <div className="topbar-left"><button ref={menuButton} className="icon-button menu-toggle" aria-label="Open navigation" onClick={() => drawer.current?.showModal()}><Menu size={21} aria-hidden="true" /></button><span className="breadcrumb"><span>Workspace</span><ChevronRight size={14} aria-hidden="true" /><strong>{screenLabel}</strong></span></div>
          <div className="header-controls"><span className="demo-badge"><FlaskConical size={13} aria-hidden="true" />Sample data</span><span className="control-divider" />
            <label className="currency-select"><Globe2 size={15} aria-hidden="true" /><span className="sr-only">Display currency</span><select value={preferences.currency} onChange={event => setPreferences({ ...preferences, currency: event.target.value as Currency })}><option value="INR">INR</option><option value="USD">USD</option></select></label>
            <button className="icon-button" aria-label={preferences.hidden ? 'Show amounts' : 'Hide amounts'} aria-pressed={preferences.hidden} title={preferences.hidden ? 'Show amounts' : 'Hide amounts'} onClick={() => setPreferences({ ...preferences, hidden: !preferences.hidden })}>{preferences.hidden ? <EyeOff size={18} aria-hidden="true" /> : <Eye size={18} aria-hidden="true" />}</button>
            <button className="icon-button" aria-label={preferences.theme === 'light' ? 'Use dark theme' : 'Use light theme'} title={preferences.theme === 'light' ? 'Use dark theme' : 'Use light theme'} onClick={() => setPreferences({ ...preferences, theme: preferences.theme === 'light' ? 'dark' : 'light' })}>{preferences.theme === 'light' ? <Moon size={18} aria-hidden="true" /> : <Sun size={18} aria-hidden="true" />}</button>
          </div>
        </header>
        <main id="main-content" tabIndex={-1}>
          {screen === 'overview' && <div className="page-heading"><div><span className="eyebrow">Your overview <span className="mobile-demo">· Sample data</span></span><h1 id="page-title" tabIndex={-1}>Everything, in perspective<span>.</span></h1><p>A clear view of your investments and everyday cash.</p></div><div className="snapshot-label"><Clock3 size={14} aria-hidden="true" /><span>Snapshot as of<strong>{AS_OF}</strong></span></div></div>}
          {demoState === 'error' && <div role="alert" className="notice error-notice"><AlertTriangle size={19} aria-hidden="true" /><div><strong>The latest snapshot couldn’t load.</strong><p>{lastGoodState === 'empty' ? 'The last demo view had no accounts.' : 'You’re still seeing the last available sample snapshot.'} This is a simulated error.</p></div><button className="outlined-button" onClick={retry} disabled={retrying}><RefreshCw size={14} className={retrying ? 'spinning' : ''} aria-hidden="true" />{retrying ? 'Retrying…' : 'Retry demo'}</button></div>}
          {screen === 'unavailable' ? <section className="empty-state"><span className="eyebrow">Local prototype · Sample data</span><h1 id="page-title" tabIndex={-1}>This view is unavailable.</h1><p>Overview, Investments, Banking, and Budgets are the available screens.</p><a className="primary-button" href="#/investments">Go to investments</a><a className="text-button" href="#/banking">Go to banking</a></section>
            : screen === 'banking' || (route.screen === 'transaction' && transactionOrigin === 'banking') ? <Banking view={view} categoryControls={categoryControls} onCategoryControls={setCategoryControls} transferState={transferState} transferControls={transferControls} onTransferControls={next => { if (next.view !== transferControls.view) setCategoryControls(current => ({ ...current, ids: [], preview: null })); setTransferControls(next) }} onTransferAction={reviewTransfer} controls={bankingControls} onChange={setBankingControls} filtersOpen={bankingFiltersOpen} onToggleFilters={() => setBankingFiltersOpen(open => !open)} onReset={() => changeState('populated')} onOpen={openTransaction} transactionId={route.screen === 'transaction' ? route.transactionId : undefined} onClose={() => navigate('banking')} onTogglePrivacy={() => setPreferences(current => ({ ...current, hidden: !current.hidden }))} />
            : screen === 'budgets' || (route.screen === 'transaction' && transactionOrigin === 'budgets') ? <Budgets recurringState={recurringState} recurringControls={recurringControls} onRecurringControls={setRecurringControls} onRecurringAction={action => { if (view !== 'loading' && view !== 'empty') setRecurringState(current => changeRecurring(current, action, getBankTransactions(partial, null), transferState)) }} tab={budgetTab} onTab={setBudgetTab} cashControls={cashControls} onCashControls={setCashControls} view={view} state={budgetState} review={transferState} expanded={budgetExpanded} onExpand={setBudgetExpanded} onAction={action => setBudgetState(current => changeBudgets(current, action))} onReviewAction={reviewTransfer} onReset={() => changeState('populated')} onReview={() => { setCategoryControls({ ...initialCategoryControls }); setTransferControls(current => ({ ...current, view: 'categories', selected: null })); navigate('banking') }} onOpen={openTransaction} transactionId={route.screen === 'transaction' ? route.transactionId : undefined} onClose={() => navigate('budgets')} onTogglePrivacy={() => setPreferences(current => ({ ...current, hidden: !current.hidden }))} />
            : route.screen === 'holding' ? <HoldingDetail holdingId={route.holdingId} view={view} onBack={() => navigate('investments')} onReset={() => changeState('populated')} />
            : screen === 'investments' ? <Investments view={view} controls={holdingsControls} onChange={setHoldingsControls} onReset={() => changeState('populated')} onOpen={openHolding} filtersOpen={holdingsFiltersOpen} onToggleFilters={() => setHoldingsFiltersOpen(open => !open)} />
            : view === 'loading' ? <LoadingState /> : view === 'empty' ? <EmptyState reset={() => changeState('populated')} /> : <>
            <Summary positions={positions} />
            <div className={`coverage-strip ${partial ? 'needs-attention' : ''}`}>
              <div><span className="coverage-icon">{partial ? <AlertTriangle size={16} aria-hidden="true" /> : <Check size={16} aria-hidden="true" />}</span><span>{partial ? <><strong>Three items need a closer look.</strong><span> Your totals show known values only.</span></> : <><strong>Six accounts. One clear picture.</strong><span> All values are fictional demo snapshots.</span></>}</span></div>
              <button className="text-button" aria-expanded={attentionOpen} aria-controls={attentionId} onClick={() => setAttentionOpen(!attentionOpen)}>{partial ? 'Review coverage' : 'About this view'}<ChevronDown size={14} aria-hidden="true" /></button>
            </div>
            <div id={attentionId} className="coverage-detail" hidden={!attentionOpen}>{partial ? <><strong>What needs attention</strong><ul><li>Advisor funds: the 20 Oct NAV is missing. One regular-plan holding is excluded from totals and allocation.</li><li>UBS: holdings are dated 17 Oct, while prices are dated 20 Oct. The last known holding value remains included and may be stale.</li><li>SBI: activity is stale and incomplete. The separately dated bank balance remains included; inspect Banking for the reconciliation gap.</li></ul></> : <><strong>Understand your coverage</strong><p>Tracked assets combine valued investments and cash once each. Liabilities are not included, so this is not net worth. Select an account below to inspect its holdings and price dates.</p></>}<p>These are sample records, not live connections. {preferences.hidden ? 'Demo exchange rate details are hidden.' : 'Demo FX: 1 USD = ₹83.50, dated 20 Oct 2026. This is not a live quote.'}</p></div>
            <div className="charts-grid"><ValueChart partial={partial} /><Allocation positions={positions} /></div>
            <div className="details-grid"><AccountsPanel positions={positions} partial={partial} /><RecentActivity partial={partial} review={transferState} /></div>
          </>}
          <footer className="overview-footer"><div><ShieldCheck size={14} aria-hidden="true" /><span>Local prototype · Fictional data only</span></div><span>{preferences.hidden ? 'Demo FX rate hidden' : 'Demo FX · 1 USD = ₹83.50'} · {FX_DATE}</span></footer>
          <section className="demo-controls" aria-label="Demo controls"><div><SlidersHorizontal size={17} aria-hidden="true" /><div><strong>Explore the demo</strong><span>See how this view handles different states.</span></div></div><label htmlFor="demo-state">Demo state<select id="demo-state" value={demoState} onChange={event => changeState(event.target.value as DemoState)}><option value="populated">Populated</option><option value="loading">Loading</option><option value="empty">Empty</option><option value="partial">Partial / stale</option><option value="error">Failed load</option></select></label></section>
        </main>
      </div>
    </div>
    <dialog ref={drawer} className="nav-drawer" aria-label="Navigation" onKeyDown={containDrawerFocus} onCancel={closeDrawer} onClose={finishDrawerClose} onClick={event => { if (event.target === drawer.current) closeDrawer() }}><div className="drawer-body"><div className="drawer-header"><Brand /><button className="icon-button" onClick={closeDrawer} aria-label="Close navigation"><X size={21} aria-hidden="true" /></button></div><Navigation screen={navScreen} navigate={navigate} onNavigate={navigateFromDrawer} /><p className="drawer-note"><ShieldCheck size={16} aria-hidden="true" />Local demo · Fictional data</p></div></dialog>
  </DisplayContext.Provider>
}
