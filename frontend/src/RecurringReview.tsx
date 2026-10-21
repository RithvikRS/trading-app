import { useContext } from 'react'
import { ArrowUpRight, CalendarDays, Check, ChevronDown, Repeat2, ShieldCheck, Undo2 } from 'lucide-react'
import { Amount, DisplayContext, PrivateValue } from './display'
import { bankCategories, bankNames } from './data/banking'
import type { BankTransaction } from './data/banking'
import { bankCoverage, cashMonths, monthNames } from './data/cashFlow'
import type { CashMonth } from './data/cashFlow'
import { recurringOverview } from './data/recurring'
import type { RecurringAction, RecurringControls, RecurringState } from './data/recurring'
import { effectiveClassification } from './data/transfers'
import type { TransferState } from './data/transfers'
import { recordDate } from './holdingPresentation'

interface Props {
  view: 'populated' | 'partial' | 'empty' | 'loading'; records: BankTransaction[]; review: TransferState
  state: RecurringState; controls: RecurringControls; onChange: (value: RecurringControls) => void
  onAction: (action: RecurringAction) => void; onOpen: (id: string) => void; onReset: () => void
}
function ObservedAmount({ min, max }: { min: bigint | null; max: bigint | null }) {
  const { hidden } = useContext(DisplayContext)
  if (min === null || max === null) return <>Unavailable</>
  if (hidden) return <PrivateValue>{null}</PrivateValue>
  return <><Amount value={{ currency: 'INR', minor: min }} />{min !== max && <> – <Amount value={{ currency: 'INR', minor: max }} /></>}</>
}
export default function RecurringReview({ view, records, review, state, controls, onChange, onAction, onOpen, onReset }: Props) {
  const { currency } = useContext(DisplayContext)
  if (view === 'loading') return <section className="holdings-loading" aria-busy="true" aria-label="Loading recurring expenses"><span role="status" className="sr-only">Loading sample recurring expenses</span><div className="skeleton-panel">{[0, 1, 2].map(row => <div key={row} className="skeleton holding-skeleton-row" />)}</div></section>
  if (view === 'empty') return <section className="empty-state"><Repeat2 size={36} aria-hidden="true" /><h2>No recurring evidence loaded.</h2><p>Explore the fictional history to review possible monthly patterns.</p><button className="primary-button" onClick={onReset}>Explore sample recurring expenses</button></section>
  const result = recurringOverview(records, review, state, controls.month, bankCoverage(view === 'partial'))
  if (!result) return <section className="empty-state"><h2>This month is unavailable.</h2><p>Recurring evidence is supplied for August–October 2026.</p></section>
  const rows = result.rows.filter(row => controls.filter === 'all' || (controls.filter === 'suggestions' ? !row.decision : row.decision === controls.filter))
    .sort((a, b) => Number(b.due > '2026-10-20') - Number(a.due > '2026-10-20') || a.due.localeCompare(b.due))
  function sourceLink(item: BankTransaction, patternId: string, label: string) {
    return <li key={item.id}><a id={`recurring-link-${patternId}-${item.id}`} href={`#/banking/${item.id}`} onClick={event => { if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return; event.preventDefault(); onOpen(item.id) }}><span><strong>{item.description}</strong><small>{recordDate(item.date)} · {item.id} · {label}</small></span><ArrowUpRight size={14} aria-hidden="true" /></a><span><Amount value={item.amount} /><small>{bankCategories[effectiveClassification(item, records, review).category]}</small></span></li>
  }
  return <div className="recurring-workspace">
    <div className="cash-toolbar"><div><span className="eyebrow">Patterns, with perspective</span><h2 id="recurring-title" tabIndex={-1}>The rhythm of your month.</h2><p>Review the evidence. Keep the commitments that make sense to you.</p></div><label className="holding-select">Recurring month<select value={controls.month} onChange={event => onChange({ ...controls, month: event.target.value as CashMonth })}>{cashMonths.map(month => <option key={month} value={month}>{monthNames[month]}</option>)}</select></label></div>
    <section className="budget-summary recurring-summary" aria-label="Recurring summary">
      <div className="budget-summary-plan"><span>{result.historical ? 'Historical month' : 'Fixed expected commitments'}</span><strong>{result.historical ? 'Evidence only' : result.fixedCount ? <Amount value={result.fixed} /> : 'None included'}</strong><small>{result.historical ? 'Recorded occurrences below · No forecast' : `${result.fixedCount} fixed ${result.fixedCount === 1 ? 'pattern' : 'patterns'} · 21–31 October only`}</small></div>
      <div><span>Variable commitments</span><strong>{result.historical ? 'Evidence only' : `${result.variableCount} expected`}</strong><small>Observed ranges · Excluded from the fixed total</small></div>
      <div><span>Reviewed patterns</span><strong>{result.reviewed} confirmed</strong><small>{result.needsReview} {result.needsReview === 1 ? 'pattern needs' : 'patterns need'} review · Across supplied history</small></div>
    </section>
    {currency !== 'INR' && <p className="budget-fx-note">Display equivalents use dated demo FX. Original INR amounts determine every range and total.</p>}
    <div className="cash-coverage"><ShieldCheck size={20} aria-hidden="true" /><div><strong>Source records through 20 October, 10:00 IST.</strong><p>{view === 'partial' ? 'SBI coverage is incomplete for 19–20 October; its missing maintenance bill stays unknown. ' : 'August and September cover full months; October is month-to-date. '}A repeated payment suggests a pattern, not a contract. Expected commitments do not reduce balances, spending, or budget remaining.</p></div></div>
    {!result.historical && <section className="panel recurring-upcoming" aria-labelledby="recurring-upcoming-title"><div className="cash-section-heading"><div><span className="eyebrow">The rest of October</span><h2 id="recurring-upcoming-title">Expected commitments</h2><p>Only confirmed, valid patterns due after the sample cutoff. Pending sources are separate.</p></div><CalendarDays size={22} aria-hidden="true" /></div>
      {result.expected.length ? <ul>{result.expected.map(row => <li key={row.pattern.id}><div className="recurring-date"><strong>{row.due.slice(-2)}</strong><span>OCT</span></div><div><strong>{row.pattern.name}</strong><small>{bankNames[row.pattern.accountId]} · Expected · {row.pattern.kind === 'fixed' ? 'Fixed amount' : 'Observed range, not an estimate'}</small></div><strong><ObservedAmount min={row.evidence.min} max={row.evidence.max} /></strong></li>)}</ul> : <p className="recurring-empty">No eligible confirmed commitments for the rest of this month. Review the supplied suggestions below; this does not mean there are no upcoming expenses.</p>}
    </section>}
    <section className="panel recurring-patterns" aria-labelledby="recurring-patterns-title">
      <div className="cash-section-heading"><div><span className="eyebrow">A decision grounded in evidence</span><h2 id="recurring-patterns-title" tabIndex={-1}>Monthly patterns</h2><p>Open a pattern to inspect its dates, amounts, and original records.</p></div><div className="budget-history"><button className="outlined-button" disabled={!state.history.length} onClick={() => onAction({ type: 'undo' })}><Undo2 size={14} aria-hidden="true" />Undo recurring change</button><button className="text-button" onClick={() => onAction({ type: 'reset' })}>Reset sample recurring decisions</button></div></div>
      <div className="recurring-filter"><label className="holding-select">Pattern review<select value={controls.filter} onChange={event => onChange({ ...controls, filter: event.target.value as RecurringControls['filter'], expanded: null })}><option value="all">All patterns</option><option value="suggestions">Suggestions</option><option value="confirmed">Confirmed</option><option value="dismissed">Dismissed</option></select></label><span>{rows.length} of {result.rows.length} supplied patterns · Both accounts</span></div>
      {state.message && <p className="budget-announcement" role={state.error ? 'alert' : 'status'}>{state.message}</p>}
      <ul className="recurring-rows">{rows.map(row => {
        const { pattern, evidence, decision } = row, expanded = controls.expanded === pattern.id
        const reviewLabel = row.needsReview ? decision === 'confirmed' ? 'Needs review · Confirmation retained' : decision === 'dismissed' ? 'Dismissed · Needs review' : 'Needs review' : decision === 'confirmed' ? 'Confirmed recurring' : decision === 'dismissed' ? 'Dismissed' : 'Suggestion'
        return <li key={pattern.id} className={expanded ? 'expanded' : ''}>
          <div className="recurring-row"><button className="recurring-disclosure" id={`recurring-pattern-${pattern.id}`} aria-expanded={expanded} aria-controls={`recurring-detail-${pattern.id}`} onClick={() => onChange({ ...controls, expanded: expanded ? null : pattern.id })}><span className="recurring-icon">{decision === 'confirmed' && !row.needsReview ? <Check size={18} aria-hidden="true" /> : <Repeat2 size={18} aria-hidden="true" />}</span><span><strong>{pattern.name}</strong><small>{bankNames[pattern.accountId]} · {pattern.payee}</small><span className={`recurring-badge ${row.needsReview ? 'warning-text' : ''}`}>{reviewLabel}</span></span><ChevronDown className={expanded ? 'rotated' : ''} size={16} aria-hidden="true" /></button>
            <div className="recurring-observed"><small>{pattern.kind === 'fixed' && evidence.min === evidence.max ? 'Observed amount' : 'Observed range'}</small><strong><ObservedAmount min={evidence.min} max={evidence.max} /></strong><small>{evidence.observations.filter(item => item.valid).length} eligible monthly records</small></div>
            <div className="recurring-occurrence"><strong>{row.status}</strong><small>Schedule · {recordDate(row.due)}</small>{row.status === 'Unknown' && <small>Missing or incomplete evidence</small>}{row.status === 'Pending source' && <small>Not a recorded expense occurrence</small>}</div>
          </div>
          {expanded && <div className="recurring-detail" id={`recurring-detail-${pattern.id}`} role="region" aria-label={`${pattern.name} evidence`}>
            <p>{pattern.reason}</p><dl><div><dt>Account & owner</dt><dd>{bankNames[pattern.accountId]} · Sample owner</dd></div><div><dt>Interval</dt><dd>Monthly · Day {pattern.day}</dd></div><div><dt>Supplied payee</dt><dd>{pattern.payee}</dd></div></dl>
            {evidence.issues.length > 0 && <div className="recurring-issues"><strong>Needs review</strong><ul>{evidence.issues.map(issue => <li key={issue}>{issue}</li>)}</ul><p>{decision === 'confirmed' ? 'Your confirmation is retained. This pattern is excluded from expected totals until its evidence is valid again.' : 'This pattern cannot be confirmed while evidence needs review.'}</p></div>}
            <h3>Supporting occurrences</h3><p>Only eligible posted expenses establish recurrence. These are gross source amounts; refunds remain separate in actual spending.</p><ul className="recurring-sources">{evidence.observations.map(occurrence => occurrence.item ? sourceLink(occurrence.item, pattern.id, occurrence.valid ? 'Recorded occurrence' : 'Ineligible occurrence') : <li key={occurrence.id}><span><strong>Source unavailable · {occurrence.id}</strong><small>{occurrence.month} · Unknown, not unpaid</small></span></li>)}</ul>
            {evidence.related.length > 0 && <><h3>Unassigned October sources</h3><p>These possible matches are not recurring occurrences. Pending does not mean paid.</p><ul className="recurring-sources">{evidence.related.map(item => item.item ? sourceLink(item.item, pattern.id, item.item.status === 'pending' ? 'Pending source' : 'Unassigned posted purchase') : <li key={item.id}>Source unavailable · {item.id}</li>)}</ul></>}
            <div className="recurring-actions">{!decision && <button className="primary-button" disabled={!evidence.valid} onClick={() => onAction({ type: 'confirm', id: pattern.id, evidence: evidence.key })}><Check size={14} aria-hidden="true" />Confirm recurring</button>}{decision === 'dismissed' ? <button className="outlined-button" onClick={() => onAction({ type: 'restore', id: pattern.id, evidence: evidence.key })}>Restore suggestion</button> : <button className="outlined-button" onClick={() => onAction({ type: 'dismiss', id: pattern.id, evidence: evidence.key })}>Dismiss suggestion</button>}<span>Review only · No payment is created</span></div>
          </div>}
        </li>
      })}</ul>
      {!rows.length && <p className="recurring-empty">No patterns match this review filter. Choose All patterns to see the supplied evidence.</p>}
      <p className="budget-local-note"><ShieldCheck size={14} aria-hidden="true" />Recurring decisions stay in memory until reload. Banking and budget histories are separate.</p>
    </section>
  </div>
}
