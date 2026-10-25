import { useContext, useLayoutEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { ArrowLeft, ArrowUpRight, Clock3, CreditCard, Search, ShieldCheck } from 'lucide-react'
import { DisplayContext, ReportingAmount } from './display'
import type { DemoState } from './data/portfolio'
import type { Money } from './data/money'
import { cardCurrent, cardKinds, cardStatements, getCardActivity, reconcileCardStatement } from './data/credit-cards'
import type { CardActivity } from './data/credit-cards'
import { recordDate } from './holdingPresentation'

function Field({ label, children }: { label: string; children: ReactNode }) {
  return <div><dt>{label}</dt><dd>{children}</dd></div>
}
function Value({ value }: { value: Money | null }) {
  const { hidden } = useContext(DisplayContext)
  return value === null && !hidden ? <span className="cc-unknown">Not supplied</span> : <ReportingAmount value={value} />
}
function inspectionNote(row: CardActivity) {
  if (!row.posted) return 'Pending authorization. Excluded from every posted statement and reconciliation; it may change or disappear.'
  if (row.kind === 'instalment') return 'Treatment unresolved. The conversion and principal labels may overlap the original purchase. No spending total or future schedule is calculated.'
  if (row.kind === 'payment') return 'A liability settlement, not a second purchase expense or income. No bank match or statement allocation is confirmed. This row does not establish that a statement is paid.'
  if (row.kind === 'refund') return 'Reduces the recorded liability. The original purchase is not linked; this refund is not income and does not establish full payment.'
  return 'Source amount shown once in its posted period. No category, budget or cash-flow totals are changed by this walkthrough.'
}
export default function CreditCards({ view, onReset }: { view: Exclude<DemoState, 'error'>; onReset: () => void }) {
  const { currency, hidden } = useContext(DisplayContext)
  const [selected, setSelected] = useState<string | null>(null)
  const [inspected, setInspected] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [posting, setPosting] = useState('')
  const [kind, setKind] = useState('')
  const pendingFocus = useRef<string | null>(null)
  const statementOrigin = useRef('page-title')
  const partial = view === 'partial'
  const records = getCardActivity(partial)
  const statement = cardStatements.find(item => item.id === selected)
  const row = records.find(item => item.id === inspected)
  const available = view !== 'empty' && view !== 'loading'
  useLayoutEffect(() => {
    if (hidden) setQuery('')
    if (!available) { setInspected(null); setSelected(null) }
    if (inspected && !row) { setInspected(null); pendingFocus.current = 'cc-activity-title' }
  }, [hidden, available, inspected, row])
  useLayoutEffect(() => {
    if (pendingFocus.current) { (document.getElementById(pendingFocus.current) ?? document.getElementById('cc-activity-title') ?? document.getElementById('page-title'))?.focus(); pendingFocus.current = null }
  }, [selected, inspected, view])
  function openStatement(id: string) { statementOrigin.current = document.activeElement?.id || 'page-title'; setSelected(id); setInspected(null); pendingFocus.current = 'cc-statement-title' }
  function back() { pendingFocus.current = statementOrigin.current; setSelected(null); setInspected(null) }
  function inspect(id: string) { pendingFocus.current = 'cc-row-title'; setInspected(id) }
  function closeRow() { pendingFocus.current = `cc-row-${inspected}`; setInspected(null) }
  const periodRows = records.filter(item => !statement || item.statement === statement.id)
  const filtered = periodRows.filter(item => (!posting || (posting === 'posted') === !!item.posted) && (!kind || item.kind === kind) && (hidden || item.description.toLowerCase().includes(query.trim().toLowerCase())))
  const calculated = statement ? reconcileCardStatement(statement, records, partial) : null

  return <div className="cc-workspace">
    <div className="page-heading"><div><span className="eyebrow">Your credit cards · Sample data</span><h1 id="page-title" tabIndex={-1}>A clearer view of what’s due<span>.</span></h1><p>Statements, dated balances and the evidence behind each entry.</p></div><span className="quiet-badge"><CreditCard size={14} aria-hidden="true" />HDFC · Fictional account</span></div>
    {view === 'loading' ? <section className="holdings-loading" aria-busy="true" aria-label="Loading sample credit cards"><p role="status">Loading sample credit cards</p><div className="skeleton-panel"><div className="skeleton number" /><div className="skeleton chart" /></div></section>
      : view === 'empty' ? <section className="empty-state"><CreditCard size={36} aria-hidden="true" /><h2>No credit card evidence loaded.</h2><p>No liability or available credit can be inferred from an empty view.</p><button className="primary-button" onClick={onReset}>Explore sample credit cards</button></section>
        : <>
          <div className="cc-notice"><ShieldCheck size={17} aria-hidden="true" /><p>Fabricated walkthrough. No issuer connection or supported statement format. All balances are dated evidence; payment status remains unknown. {currency === 'USD' && 'USD is a reporting equivalent using demo FX dated 20 Oct 2026, not transaction-date FX. Original INR values are labeled separately.'}</p></div>
          {partial && <p className="cc-warning" role="status">Stale / incomplete sample: one October purchase is missing. Statement totals remain source checkpoints; reconciliation is unavailable. The current snapshot is also unavailable.</p>}
          {statement ? <section className="panel cc-statement-detail" aria-labelledby="cc-statement-title">
            <button className="text-button" onClick={back}><ArrowLeft size={15} aria-hidden="true" />Back to statement history</button>
            <div className="cc-section-title"><div><span className="eyebrow">Billing account · Everyday card</span><h2 id="cc-statement-title" tabIndex={-1}>{statement.label} statement</h2><p>{recordDate(statement.from)}–{recordDate(statement.to)} · Statement dated {recordDate(statement.date)}</p></div><span className="cc-status">Payment status unknown</span></div>
            <dl className="cc-values">
              <Field label="Source total amount due"><Value value={statement.due} /></Field>
              <Field label="Source minimum amount due"><Value value={statement.minimum} /></Field>
              <Field label="Payment due date">{recordDate(statement.dueDate)}</Field>
              <Field label="Statement closing liability"><Value value={statement.closing} /></Field>
            </dl>
            <p className="cc-explanation">Total due and closing liability describe this statement; they are not added together. Minimum due is not full settlement. A due date, payment or refund alone does not establish paid or overdue status.</p>
            <details className="cc-reconciliation"><summary>{calculated?.minor === statement.closing.minor ? 'Supplied statement reconciles' : 'Reconciliation unavailable'} · Inspect evidence</summary><dl className="cc-values">
              <Field label="Opening liability"><Value value={statement.opening} /></Field>
              <Field label="Opening + posted debits − posted credits"><Value value={calculated} /></Field>
              <Field label="Closing minus calculated"><Value value={calculated ? { currency: statement.closing.currency, minor: statement.closing.minor - calculated.minor } : null} /></Field>
              <Field label="Source">Fictional {statement.label} statement</Field>
            </dl><p>Reconciliation covers the complete supplied statement only. Pending authorizations and later activity are excluded. A matching closing balance does not prove payment or complete account history. Filters never change these source values.</p></details>
          </section> : <>
            <section className="cc-overview" aria-label="Credit account evidence">
              <article className="panel cc-account"><div className="cc-section-title"><span className="cc-account-icon"><CreditCard size={24} aria-hidden="true" /></span><span className="cc-status">One billing account</span></div><span className="eyebrow">HDFC · INR liability</span><h2>Everyday card</h2><p>Primary and add-on examples share this account. Physical cards do not create separate balances or limits.</p><div className="cc-account-due"><span>October source total due</span><strong><Value value={cardStatements[0]!.due} /></strong><small>Statement: 15 Oct 2026 · Due: 4 Nov 2026</small></div><button className="outlined-button" id="cc-latest-statement" onClick={() => openStatement('oct')}>Inspect latest statement<ArrowUpRight size={15} aria-hidden="true" /></button><p>Payment status unknown · No allocation confirmed</p></article>
              <article className="panel cc-current" aria-labelledby="cc-current-title"><div className="cc-section-title"><div><h2 id="cc-current-title">Separately dated balance evidence</h2><p><Clock3 size={13} aria-hidden="true" />As of {cardCurrent.asOf} · Fictional snapshot</p></div></div><dl className="cc-values">
                <Field label="Reported outstanding"><Value value={partial ? null : cardCurrent.outstanding} /></Field><Field label="Reported credit limit"><Value value={partial ? null : cardCurrent.limit} /></Field><Field label="Unbilled amount"><Value value={cardCurrent.unbilled} /></Field><Field label="Available credit"><Value value={cardCurrent.available} /></Field>
              </dl><p className="cc-explanation">Outstanding is a dated observation, not a live balance or remaining statement payment. Unbilled amount and available credit were not supplied; neither is calculated from the limit or activity. Available credit is not cash. These values are not added to statement due amounts or tracked assets.</p></article>
            </section>
            <section className="panel cc-history" aria-labelledby="cc-history-title"><div className="cc-section-title"><div><h2 id="cc-history-title">Statement history</h2><p>Billing periods are not calendar months. Earlier history is unknown.</p></div><span className="quiet-badge">2 sample statements</span></div>
              {cardStatements.map(item => <div className="cc-statement-row" key={item.id}><div><button className="text-button" id={`cc-statement-${item.id}`} onClick={() => openStatement(item.id)}>{item.label}<ArrowUpRight size={14} aria-hidden="true" /></button><p>{recordDate(item.from)}–{recordDate(item.to)}</p></div><div><span>Source total due</span><strong><Value value={item.due} /></strong></div><div><span>Due {recordDate(item.dueDate)}</span><p>Payment status unknown</p></div><span className={partial || !item.complete ? 'cc-status cc-status-warning' : 'cc-status'}>{partial || !item.complete ? 'Incomplete activity' : 'Supplied period reconciles'}</span></div>)}
              <p className="cc-explanation">August and earlier statements were not supplied. Missing months do not imply zero spending or zero liability. September’s passed due date does not establish an overdue balance.</p>
            </section>
          </>}
          <section className="panel cc-activity" aria-labelledby="cc-activity-title">
            <div className="cc-section-title"><div><h2 id="cc-activity-title" tabIndex={-1}>{statement ? 'Statement activity' : 'Card activity'}</h2><p>{statement ? 'Rows assigned to this statement only.' : 'Supplied entries through 20 Oct 2026, 10:00 IST; partial history.'} No spending total is inferred.</p></div></div>
            <div className="cc-filters"><label className="holdings-search"><Search size={16} aria-hidden="true" /><span className="sr-only">Search card activity</span><input type="search" maxLength={120} autoComplete="off" spellCheck={false} placeholder={hidden ? 'Descriptions hidden' : 'Search description'} value={hidden ? '' : query} disabled={hidden} onChange={event => setQuery(event.target.value)} /></label><label className="holding-select"><span>Card posting status</span><select value={posting} onChange={event => setPosting(event.target.value)}><option value="">Posted & pending</option><option value="posted">Posted</option><option value="pending">Pending</option></select></label><label className="holding-select"><span>Entry type</span><select value={kind} onChange={event => setKind(event.target.value)}><option value="">All types</option>{Object.entries(cardKinds).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><button className="text-button" onClick={() => { setQuery(''); setPosting(''); setKind('') }}>Clear filters</button></div>
            <p className="cc-result" role="status">{filtered.length} of {periodRows.length} supplied entries · Filters do not change balances</p>
            {filtered.length === 0 ? <div className="holdings-no-results"><h3>No card entries match.</h3><p>Change the filters to inspect supplied activity. An empty result is not zero spending.</p></div> : <table className="cc-table" role="table"><caption className="sr-only">Card activity in {currency}. Positive outstanding means owed. Source debits increase liability; credits reduce it. Pending and ambiguous entries are separate.</caption><thead role="rowgroup"><tr role="row"><th scope="col" role="columnheader">Dates & status</th><th scope="col" role="columnheader">Entry</th><th scope="col" role="columnheader">Amount · {currency}</th><th scope="col" role="columnheader">Liability effect</th></tr></thead><tbody role="rowgroup">{filtered.map(item => <tr key={item.id} role="row"><td role="cell"><time dateTime={item.date}>{recordDate(item.date)}</time><small>{item.posted ? `Posted ${recordDate(item.posted)}` : 'Pending · Not posted'}</small></td><th scope="row" role="rowheader"><button id={`cc-row-${item.id}`} className="cc-entry-link" onClick={() => inspect(item.id)}><span className="sr-only">Inspect entry {item.id.slice(1)}: </span><span>{hidden ? 'Description hidden' : item.description}{' '}<small>{cardKinds[item.kind]}</small></span><ArrowUpRight size={14} aria-hidden="true" /></button></th><td role="cell"><Value value={item.amount} /></td><td role="cell">{item.effect === 'unresolved' ? 'Unresolved / pending' : `${item.effect === 'increases' ? 'Debit · Increases' : 'Credit · Reduces'} liability`}</td></tr>)}</tbody></table>}
            <p className="cc-explanation">Payments settle liability; they are not another expense. Refunds are not income. Instalment labels remain unresolved to avoid counting principal twice. No bank matches or category decisions are made here.</p>
          </section>
          {row && <section className="panel cc-inspection" aria-labelledby="cc-row-title"><div className="cc-section-title"><div><span className="eyebrow">Source inspection · Fabricated evidence</span><h2 id="cc-row-title" tabIndex={-1}>Entry {row.id.slice(1)} details</h2></div><button className="outlined-button" onClick={closeRow}>Close source inspection</button></div><dl className="cc-values"><Field label="Description">{hidden ? 'Description hidden' : row.description}</Field><Field label="Original narration">{hidden ? 'Narration hidden' : row.narration}</Field><Field label="Source amount"><Value value={row.amount} /></Field><Field label="Entry type">{cardKinds[row.kind]}</Field><Field label="Transaction date">{recordDate(row.date)}</Field><Field label="Posting date">{row.posted ? recordDate(row.posted) : 'Not posted'}</Field><Field label="Source">{row.statement ? `Fictional ${cardStatements.find(item => item.id === row.statement)?.label} statement` : 'Fictional later-activity sample'}</Field><Field label="Source meaning">{row.effect === 'unresolved' ? 'Interpretation unresolved' : row.effect === 'increases' ? 'Debit increases liability' : 'Credit reduces liability'}</Field></dl><p className="cc-warning">{inspectionNote(row)}</p></section>}
        </>}
  </div>
}
