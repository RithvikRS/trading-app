import { useContext, useEffect, useState } from 'react'
import { ArrowUpRight, CalendarDays, ChevronDown, EyeOff, Pencil, PieChart, ShieldCheck, Undo2 } from 'lucide-react'
import { Amount, DisplayContext, ReportingAmount } from './display'
import { bankCategories, bankNames, getBankSnapshots, getBankTransactions } from './data/banking'
import type { BankCategory } from './data/banking'
import { budgetOverview, budgetStatus } from './data/budgets'
import type { BudgetAction, BudgetState } from './data/budgets'
import type { TransferAction, TransferState } from './data/transfers'
import { recordDate } from './holdingPresentation'
import CashFlow from './CashFlow'
import RecurringReview from './RecurringReview'
import type { RecurringAction, RecurringControls, RecurringState } from './data/recurring'
import type { CashControls } from './data/cashFlow'
import BudgetEditor from './BudgetEditor'
import TransactionInspector from './TransactionInspector'

interface Props {
  recurringState: RecurringState; recurringControls: RecurringControls; onRecurringControls: (value: RecurringControls) => void; onRecurringAction: (action: RecurringAction) => void
  tab: 'monthly' | 'cash' | 'recurring'; onTab: (tab: 'monthly' | 'cash' | 'recurring') => void; cashControls: CashControls; onCashControls: (value: CashControls) => void
  view: 'populated' | 'partial' | 'empty' | 'loading'; state: BudgetState; review: TransferState
  expanded: BankCategory | null; onExpand: (value: BankCategory | null) => void
  onAction: (action: BudgetAction) => void; onReviewAction: (action: TransferAction) => void
  onReset: () => void; onReview: () => void; onOpen: (id: string) => void
  transactionId?: string; onClose: () => void; onTogglePrivacy: () => void
}
export default function Budgets({ recurringState, recurringControls, onRecurringControls, onRecurringAction, tab, onTab, cashControls, onCashControls, view, state, review, expanded, onExpand, onAction, onReviewAction, onReset, onReview, onOpen, transactionId, onClose, onTogglePrivacy }: Props) {
  const { hidden, currency } = useContext(DisplayContext)
  const [editor, setEditor] = useState<BankCategory | null>(null)
  const unavailable = view === 'empty' || view === 'loading'
  const records = unavailable ? [] : getBankTransactions(view === 'partial', null)
  const totals = budgetOverview(state, records, review, view === 'partial')
  const over = totals.remaining.minor < 0n
  useEffect(() => { if (unavailable) setEditor(null) }, [unavailable])
  return <>
    <div className="page-heading"><div><span className="eyebrow">Your monthly plan <span className="mobile-demo">· Sample data</span></span><h1 id="page-title" tabIndex={-1}>Make room for what matters<span>.</span></h1><p>{tab === 'cash' ? 'See where money comes from, where it goes, and what the records explain.' : tab === 'recurring' ? 'Review repeating expenses against their original records.' : 'Category limits, grounded in your recorded spending.'}</p></div>{tab === 'monthly' && <div className="budget-month"><CalendarDays size={18} aria-hidden="true" /><div><strong>October 2026</strong><span>Full-month limits · HDFC & SBI</span></div></div>}</div>
    <div className="budget-views" aria-label="Budget views"><button aria-pressed={tab === 'monthly'} onClick={() => onTab('monthly')}>Monthly budgets</button><button aria-pressed={tab === 'cash'} onClick={() => onTab('cash')}>Cash flow</button><button aria-pressed={tab === 'recurring'} onClick={() => onTab('recurring')}>Recurring</button></div>
    {tab === 'recurring' ? <RecurringReview view={view} records={records} review={review} state={recurringState} controls={recurringControls} onChange={onRecurringControls} onAction={onRecurringAction} onOpen={onOpen} onReset={onReset} /> : tab === 'cash' ? <CashFlow view={view} records={records} review={review} controls={cashControls} onChange={onCashControls} onOpen={onOpen} onReset={onReset} /> : view === 'loading' ? <section className="holdings-loading" aria-busy="true" aria-label="Loading monthly budgets"><span className="sr-only" role="status">Loading sample budgets</span><div className="skeleton-panel"><div className="skeleton number" />{[0, 1, 2].map(row => <div key={row} className="skeleton holding-skeleton-row" />)}</div></section>
      : view === 'empty' ? <section className="empty-state"><PieChart size={36} aria-hidden="true" /><h2>No banking data loaded.</h2><p>Monthly budgets need source activity. Explore the fictional sample to start a plan.</p><button className="primary-button" onClick={onReset}>Explore sample budgets</button></section> : <>
        <section className="budget-summary" aria-label="Monthly budget summary">
          <div className="budget-summary-plan"><span>Planned category limits</span><strong>{totals.count ? <Amount value={totals.planned} /> : 'No budgets set'}</strong><small>{totals.count} of {totals.rows.length} categories · Full October limits</small></div>
          <div><span>Spending in budgeted categories</span><strong>{totals.count ? <Amount value={totals.spent} /> : 'No categories budgeted'}</strong><small>Net of verified refunds · Available activity</small></div>
          <div><span>{totals.provisional ? 'Provisional ' : ''}{over ? 'over limit' : 'remaining'}</span><strong>{totals.count ? <Amount value={{ ...totals.remaining, minor: over ? -totals.remaining.minor : totals.remaining.minor }} /> : 'Set a category limit'}</strong><small>Limit minus net spending · Not available cash</small></div>
        </section>
        {currency !== 'INR' && <p className="budget-fx-note">Display equivalents use dated demo FX. Totals use original INR arithmetic; independently rounded values may differ.</p>}
        <section className="budget-coverage panel" aria-labelledby="budget-coverage-title">
          <div><ShieldCheck size={19} aria-hidden="true" /><div><h2 id="budget-coverage-title">{view === 'partial' ? 'Source coverage is incomplete.' : 'Activity through 20 October, 10:00 IST.'}</h2><p>{view === 'partial' ? 'SBI activity is stale and missing a bill; balance snapshots stay unchanged.' : 'Both statements cover 1–20 October. Later days are not yet supplied.'} {totals.unresolved > 0 ? 'Some posted movements still need classification.' : 'All available posted movements are classified.'}</p></div><a className="text-button" href="#/banking" onClick={event => { if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return; event.preventDefault(); onReview() }}>Review categories<ArrowUpRight size={14} aria-hidden="true" /></a></div>
          <details><summary>Coverage & calculation details</summary><div className="budget-coverage-values"><span>Unresolved outgoing <strong><Amount value={totals.outgoing} /></strong></span><span>Unresolved incoming <strong><Amount value={totals.incoming} /></strong></span><span>{totals.unresolved} unresolved posted records · {totals.pending} pending</span></div><p>Pending records, confirmed transfers, and investment funding are excluded. Refunds offset their purchase category in the refund's booking month. Limits are not prorated. {totals.provisional ? 'Remaining amounts and statuses are provisional; missing or unresolved activity can change them. A zero is only the observed amount.' : 'Actuals cover the supplied month-to-date period only.'}</p></details>
        </section>
        <section className="panel budget-categories" aria-labelledby="budget-categories-title">
          <div className="budget-section-heading"><div><span className="eyebrow">A little structure, more clarity</span><h2 id="budget-categories-title" tabIndex={-1}>Your categories</h2><p>Expand a category to see the records behind its spending.</p></div><div className="budget-history"><button className="outlined-button" disabled={!state.history.length} onClick={() => onAction({ type: 'undo' })}><Undo2 size={14} aria-hidden="true" />Undo budget change</button><button className="text-button" onClick={() => { onAction({ type: 'reset' }); onExpand(null) }}>Reset sample budgets</button></div></div>
          {state.message && <p className="budget-announcement" role="status">{state.message}</p>}
          {!totals.count && <p className="budget-announcement">No budgets set. Add a limit to any category; all actual spending remains visible.</p>}
          <div className="budget-column-head" aria-hidden="true"><span>Category</span><span>Monthly limit · {currency}</span><span>Net spending · {currency}</span><span>Remaining / over · {currency}</span><span>Edit</span></div>
          <ul className="budget-rows">{totals.rows.map(row => {
            const open = expanded === row.category, overLimit = (row.remaining?.minor ?? 0n) < 0n
            const percentage = row.limit && row.limit.minor > 0n && row.net.minor >= 0n ? Number(row.net.minor) / Number(row.limit.minor) * 100 : null
            return <li key={row.category} className={`budget-row ${open ? 'expanded' : ''}`}>
              <div className="budget-row-main">
                <div className="budget-category-name"><button id={`budget-category-${row.category}`} className="budget-disclosure" aria-expanded={open} aria-controls={`budget-detail-${row.category}`} onClick={() => onExpand(open ? null : row.category)}><ChevronDown size={16} className={open ? 'rotated' : ''} aria-hidden="true" /><strong>{bankCategories[row.category]}</strong></button><span className={overLimit ? 'warning-text' : ''}>{budgetStatus(row.net.minor, row.limit?.minor, totals.provisional)}</span>
                  {hidden ? <span className="budget-progress-hidden"><EyeOff size={12} aria-hidden="true" />Progress hidden</span> : row.limit && <div className="budget-progress-wrap"><div className="budget-progress" aria-hidden="true"><span style={{ width: `${Math.min(100, Math.max(0, percentage ?? 0))}%` }} /></div><small>{percentage === null ? row.net.minor < 0n ? 'Refund exceeds purchases' : 'Zero-spend target' : `${percentage.toFixed(1)}% of limit`}</small></div>}
                </div>
                <div className="budget-metric"><span>Monthly limit</span><strong>{row.limit ? <Amount value={row.limit} /> : 'Not set'}</strong></div>
                <div className="budget-metric"><span>Net spending</span><strong><Amount value={row.net} /></strong>{totals.provisional && row.net.minor === 0n && <small>Observed · Incomplete</small>}</div>
                <div className="budget-metric"><span>{totals.provisional ? 'Provisional ' : ''}{overLimit ? 'over limit' : 'remaining'}</span><strong>{row.remaining ? <Amount value={{ ...row.remaining, minor: overLimit ? -row.remaining.minor : row.remaining.minor }} /> : 'No limit'}</strong></div>
                <button id={`budget-edit-${row.category}`} className="budget-edit icon-button" aria-label={`${row.limit ? 'Edit' : 'Set'} ${bankCategories[row.category]} budget`} onClick={() => setEditor(row.category)}><Pencil size={16} aria-hidden="true" /></button>
              </div>
              {open && <div id={`budget-detail-${row.category}`} className="budget-detail" role="region" aria-label={`${bankCategories[row.category]} spending details`}>
                <dl><div><dt>Gross expenses</dt><dd><Amount value={row.gross} /></dd></div><div><dt>Verified refunds</dt><dd><Amount value={row.refunded} /></dd></div><div><dt>Net classified spending</dt><dd><Amount value={row.net} /></dd></div></dl>
                <p>{row.records.length} contributing {row.records.length === 1 ? 'record' : 'records'} · Posted in the supplied October period{totals.provisional ? ' · Incomplete classification or coverage' : ''}</p>
                <ul>{row.records.map(item => <li key={item.id}><a id={`budget-link-${item.id}`} href={`#/banking/${item.id}`} onClick={event => { if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return; event.preventDefault(); onOpen(item.id) }}><span><strong>{item.description}</strong><small>{bankNames[item.accountId]} · {recordDate(item.date)} · {row.refundIds.has(item.id) ? 'Verified refund' : 'Expense'}</small></span><ArrowUpRight size={14} aria-hidden="true" /></a><ReportingAmount value={item.amount} /></li>)}</ul>
                {!row.records.length && <p>{totals.provisional ? 'No classified records are currently available here. This does not establish zero spending.' : 'No posted spending or verified refunds in this category during the supplied period.'}</p>}
                {row.net.minor < 0n && <p>Net refunds exceed purchases in this period. Remaining can exceed the original limit.</p>}
              </div>}
            </li>
          })}</ul>
          <div className="budget-unbudgeted"><div><span>Spending without a category limit</span><strong><Amount value={totals.unbudgeted} /></strong><small>Available net actuals · {totals.rows.length - totals.count} categories without limits</small></div><div><span>All classified spending</span><strong><Amount value={totals.total} /></strong><small>Budgeted + unbudgeted · Not complete spending</small></div></div>
          <p className="budget-local-note"><ShieldCheck size={14} aria-hidden="true" />Limits and budget history stay in memory until reload. Banking reviews have their own undo and reset.</p>
        </section>
      </>}
    {editor && !unavailable && <BudgetEditor key={editor} category={editor} limit={state.limits[editor]} onAction={onAction} onClose={() => setEditor(null)} onTogglePrivacy={onTogglePrivacy} />}
    {transactionId && <TransactionInspector key={transactionId} id={transactionId} records={records} snapshots={getBankSnapshots(view === 'partial', null)} review={review} onReviewAction={onReviewAction} loading={view === 'loading'} onClose={onClose} onTogglePrivacy={onTogglePrivacy} />}
  </>
}
