import { useContext } from 'react'
import type { MouseEvent, ReactNode } from 'react'
import { ArrowDownLeft, ArrowLeft, ArrowUpRight, Check, ChevronRight, Clock3, FileText, Layers3, ReceiptText, ShieldCheck, Wallet } from 'lucide-react'
import { Amount, DisplayContext, PrivateValue } from './display'
import { getHoldings, holdingsTotal, holdingWeight, QUOTE_SCALE, UNIT_SCALE } from './data/holdings'
import { getEmployeeLots, getHoldingActivity } from './data/holdingRecords'
import { convert, formatFixed } from './data/money'
import type { Currency } from './data/money'
import { FX_DATE } from './data/portfolio'
import { accountName, recordDate, sourceTimestamp, typeLabels } from './holdingPresentation'

function Quantity({ value }: { value: bigint }) { return <PrivateValue><span className="detail-quantity">{formatFixed(value, UNIT_SCALE)}</span></PrivateValue> }
function QuoteValue({ value, currency }: { value: bigint; currency: Currency }) { return <PrivateValue><span className="detail-quote">{currency === 'INR' ? '₹' : '$'}{formatFixed(value, QUOTE_SCALE, 2)}</span></PrivateValue> }
function Field({ label, children }: { label: string; children: ReactNode }) { return <div><dt>{label}</dt><dd>{children}</dd></div> }

interface Props { holdingId: string; view: 'populated' | 'partial' | 'loading' | 'empty'; onBack: () => void; onReset: () => void }
export default function HoldingDetail({ holdingId, view, onBack, onReset }: Props) {
  const { currency } = useContext(DisplayContext)
  const holdings = getHoldings(view === 'partial')
  const holding = holdings.find(item => item.id === holdingId)
  function back(event: MouseEvent<HTMLAnchorElement>) {
    if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return
    event.preventDefault(); onBack()
  }
  const backLink = <a className="detail-back" href="#/investments" onClick={back}><ArrowLeft size={15} aria-hidden="true" />Back to holdings</a>
  if (view === 'loading') return <>{backLink}<h1 id="page-title" tabIndex={-1} className="detail-state-title">Holding details</h1><section className="detail-loading" aria-busy="true" aria-label="Loading holding details"><span role="status" className="sr-only">Loading sample holding</span><div className="skeleton-panel"><div className="skeleton number" /><div className="skeleton chart" /></div><div className="skeleton-panel"><div className="skeleton short" /><div className="skeleton chart" /></div></section></>
  if (!holding || view === 'empty') return <>{backLink}<section className="empty-state"><div className="empty-art" aria-hidden="true"><div /><Layers3 size={39} /></div><span className="eyebrow">Sample portfolio</span><h1 id="page-title" tabIndex={-1}>This holding isn’t available.</h1><p>{view === 'empty' ? 'No holdings are loaded in this sample view.' : 'Choose an available holding from the list.'}</p>{view === 'empty' && <button className="primary-button" onClick={onReset}>Load sample holding</button>}</section></>

  const { instrument } = holding
  const weight = holdingWeight(holding, holdingsTotal(holdings))
  const missing = holdings.some(item => item.value === null)
  const lots = getEmployeeLots(holding.id)
  const activity = getHoldingActivity(holding.id)
  const lotUnits = lots.reduce((total, lot) => total + lot.remainingUnits, 0n)
  const quoteLabel = instrument.type === 'fund' ? 'NAV' : 'Price'
  const warning = holding.value === null || holding.stale

  return <>
    <div className="detail-navigation"><nav aria-label="Holding breadcrumb"><a href="#/investments" onClick={back}>Investments</a><ChevronRight size={13} aria-hidden="true" /><span aria-current="page">Holding details</span></nav>{backLink}</div>
    <div className="detail-heading"><div className={`holding-mark detail-mark ${instrument.type}`} aria-hidden="true">{instrument.symbol.slice(0, 2)}</div><div className="detail-heading-copy"><span className="eyebrow">Your holding · Sample data</span><h1 id="page-title" tabIndex={-1}>{instrument.name}<span>.</span></h1><p>{instrument.symbol} <span>·</span> {instrument.market} <span>·</span> {typeLabels[instrument.type]} <span>·</span> {instrument.currency}</p></div><div className="detail-account"><span>Held with</span><strong>{accountName(holding.accountId)}</strong>{holding.employeePlan && <small>Accenture ESPP</small>}{instrument.plan && <small>{instrument.plan} · {instrument.option}</small>}</div></div>
    <div className={`detail-coverage ${warning ? 'warning-text' : ''}`}><Clock3 size={16} aria-hidden="true" /><p>{holding.value === null ? 'NAV unavailable. This holding is excluded from known investment value; its units remain recorded.' : holding.stale ? 'Holdings are stale. The last known units remain valued using the separately dated price below.' : 'Dated sample snapshot. Holdings and market quotes are recorded separately.'}</p></div>
    <div className="holding-detail-grid">
      <div className="detail-column">
        <section className="panel position-panel" aria-labelledby="position-title">
          <div className="position-hero"><div className="summary-label"><h2 id="position-title">Current position</h2><Wallet size={19} aria-hidden="true" /></div><p className="position-currency">Reporting value · {currency}</p><p className="hero-amount"><Amount value={holding.value ? convert(holding.value, 'INR') : null} /></p><p className="position-caption">{holding.value === null ? 'Value unavailable · Excluded from portfolio totals' : `Valued at the sample ${quoteLabel.toLowerCase()} · Excludes cash`}</p></div>
          <dl className="position-fields">
            <Field label={`Native value · ${instrument.currency}`}><Amount value={holding.value} original /></Field>
            <Field label="Units held"><Quantity value={holding.units} /></Field>
            <Field label={`${quoteLabel} · ${instrument.currency}`} >{holding.quote ? <QuoteValue value={holding.quote.amount} currency={instrument.currency} /> : <span>Unavailable</span>}</Field>
            <Field label="Investment weight"><span>{weight === null ? 'Unavailable' : `${weight.toFixed(1)}%`}</span></Field>
          </dl>
          <p className="detail-panel-note">Weight uses {missing ? 'known' : 'all valued'} investments across accounts, excluding cash. {missing && 'Portfolio coverage is incomplete. '}Rounded reporting values may differ by a minor unit.</p>
        </section>
        <section className="panel source-panel" aria-labelledby="source-title"><div className="detail-panel-heading"><div><h2 id="source-title">Source & freshness</h2><p>Know what each value represents.</p></div><ShieldCheck size={18} aria-hidden="true" /></div>
          <dl className="source-fields">
            <Field label="Holdings snapshot"><time dateTime={holding.holdingsDate}>{sourceTimestamp(holding.holdingsDate)}</time><small>{accountName(holding.accountId)} · Fictional holding record{holding.stale && <span className="warning-text"> · Stale</span>}</small></Field>
            <Field label={`${quoteLabel} snapshot`}>{holding.quote ? <><time dateTime={holding.quote.date}>{sourceTimestamp(holding.quote.date)}</time><small>Fictional {instrument.currency} {quoteLabel.toLowerCase()} · No live connection</small></> : <><span className="warning-text">Unavailable</span><small>No {quoteLabel.toLowerCase()} supplied in this sample.</small></>}</Field>
            <Field label="Reporting exchange rate"><PrivateValue><span>1 USD = ₹83.50</span></PrivateValue><small>Fictional rate · {FX_DATE} · Current valuation only</small></Field>
          </dl>
          <p className="detail-panel-note">Quote freshness does not establish holdings freshness. Source times are shown in IST; record dates below have no assumed execution time.</p>
        </section>
        <section className="detail-record-note" aria-labelledby="basis-title"><FileText size={19} aria-hidden="true" /><div><h2 id="basis-title">Cost basis unavailable</h2><p>Acquisition records may be incomplete. Current market value is not purchase cost. Returns and tax basis are not calculated from these samples.</p></div></section>
      </div>
      <div className="detail-column">
        {instrument.type === 'fund' && <section className="panel fund-panel" aria-labelledby="fund-title"><div className="detail-panel-heading"><div><h2 id="fund-title">Fund information</h2><p>The plan and folio behind this position.</p></div><Layers3 size={18} aria-hidden="true" /></div><dl className="fund-fields"><Field label="Plan">{instrument.plan}</Field><Field label="Option">{instrument.option}</Field><Field label="Folio">{holding.folio}</Field><Field label="Account">{accountName(holding.accountId)}</Field></dl></section>}
        {holding.employeePlan && <section className="panel lots-panel" aria-labelledby="lots-title"><div className="detail-panel-heading"><div><h2 id="lots-title">Employee purchase lots</h2><p>Accenture ESPP · Illustrative records</p></div><Layers3 size={18} aria-hidden="true" /></div><div className="lot-reconciliation"><Check size={15} aria-hidden="true" /><span>{lots.length} open lots · <Quantity value={lotUnits} /> units {lotUnits === holding.units ? 'match this holding' : 'do not match this holding'}</span></div>
          <ol className="employee-lots">{lots.map((lot, index) => <li key={lot.id}><div className="lot-heading"><span>Lot {index + 1}</span><time dateTime={lot.date}>{recordDate(lot.date)}</time></div><dl><Field label="Remaining units"><Quantity value={lot.remainingUnits} /></Field><Field label="Purchase price · USD"><QuoteValue value={lot.purchasePrice} currency="USD" /></Field><Field label="Purchase amount · USD"><Amount value={lot.purchaseAmount} original /></Field><Field label="Fee · USD">{lot.fee === null ? <span>Not supplied</span> : <Amount value={lot.fee} original />}</Field></dl></li>)}</ol>
          <p className="detail-panel-note">No disposals in these sample lots. Purchase amounts exclude separately listed fees; an unsupplied fee is unknown. Original USD amounts are retained without applying current FX to historical purchases. These are not tax-basis records.</p>
        </section>}
        <section className="panel holding-activity-panel" aria-labelledby="holding-activity-title"><div className="detail-panel-heading"><div><h2 id="holding-activity-title">Selected activity</h2><p>Sample events for this account and holding.</p></div><ReceiptText size={18} aria-hidden="true" /></div>
          {activity.length ? <ol className="holding-activity">{activity.map(event => <li key={event.id}><span className={`detail-event-icon ${event.kind}`} aria-hidden="true">{event.kind === 'dividend' ? <ArrowDownLeft size={15} /> : event.kind === 'fee' ? <ReceiptText size={15} /> : <ArrowUpRight size={15} />}</span><div className="detail-event-copy"><strong>{event.label}</strong><time dateTime={event.date}>{recordDate(event.date)}</time>{event.units !== undefined && <small><Quantity value={event.units} /> units</small>}</div><div className="detail-event-amount"><Amount value={event.amount} original /><small>{event.amount.currency} · {event.kind === 'dividend' ? 'Credit' : 'Debit'}</small></div></li>)}</ol> : <div className="detail-no-activity"><ReceiptText size={25} aria-hidden="true" /><h3>No sample activity supplied.</h3><p>This does not mean the holding has no transaction history.</p></div>}
          <p className="detail-panel-note">Selected records, not a complete ledger. Amounts retain their original currency. Purchases and fees are separate; these events do not add to the current holding value.</p>
        </section>
      </div>
    </div>
  </>
}
