import { useContext, useId, useState } from 'react'
import { ArrowDown, ArrowDownUp, ArrowUp, BarChart3, Check, Clock3, Filter, Layers3, Search, ShieldCheck, Wallet, X } from 'lucide-react'
import { Amount, DisplayContext, PrivateValue } from './display'
import { accounts, AS_OF } from './data/portfolio'
import { convert, formatFixed } from './data/money'
import {
  defaultFilters, getHoldings, holdingStatus, holdingsTotal, holdingWeight, QUOTE_SCALE, selectHoldings, UNIT_SCALE,
} from './data/holdings'
import type { Holding, HoldingFilters, HoldingsControls, InstrumentType, SortField } from './data/holdings'

const types: { value: InstrumentType | ''; label: string }[] = [
  { value: '', label: 'All holdings' }, { value: 'stock', label: 'Stocks' }, { value: 'etf', label: 'ETFs' }, { value: 'fund', label: 'Mutual funds' },
]
const typeLabels = { stock: 'Stock', etf: 'ETF', fund: 'Mutual fund' }
const investmentAccounts = accounts.filter(account => account.kind === 'investment')
function accountName(id: string) { return id === 'ind-in' ? 'INDmoney India' : accounts.find(account => account.id === id)?.name ?? 'Unknown account' }
function sourceDate(date: string) {
  return new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', timeZone: 'Asia/Kolkata' }).format(new Date(date))
}
function sourceTimestamp(date: string) {
  return new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Kolkata', hourCycle: 'h23' }).format(new Date(date)) + ' IST'
}

function HoldingIdentity({ holding }: { holding: Holding }) {
  const instrument = holding.instrument
  return <div className="holding-identity">
    <span className={`holding-mark ${instrument.type}`} aria-hidden="true">{instrument.symbol.slice(0, 2)}</span>
    <div><strong>{instrument.name}</strong><span>{instrument.symbol} · {instrument.market} · {typeLabels[instrument.type]}</span>
      {instrument.plan && <small>{instrument.plan} · {instrument.option}</small>}
    </div>
  </div>
}

function Freshness({ holding }: { holding: Holding }) {
  const status = holdingStatus(holding)
  return <div className="holding-freshness">
    <span className={`holding-status ${status !== 'complete' ? 'warning-text' : ''}`}>
      {status === 'complete' ? <Check size={12} aria-hidden="true" /> : <Clock3 size={12} aria-hidden="true" />}
      {status === 'missing' ? 'NAV missing' : status === 'stale' ? 'Holdings stale' : 'Dated snapshot'}
    </span>
    <span>Held <time dateTime={holding.holdingsDate} title={sourceTimestamp(holding.holdingsDate)}>{sourceDate(holding.holdingsDate)}</time></span>
    <span>{holding.instrument.type === 'fund' ? 'NAV' : 'Price'} {holding.quote ? <time dateTime={holding.quote.date} title={sourceTimestamp(holding.quote.date)}>{sourceDate(holding.quote.date)}</time> : 'unavailable'}</span>
  </div>
}

interface Props { view: 'populated' | 'partial' | 'loading' | 'empty'; controls: HoldingsControls; onChange: (controls: HoldingsControls) => void; onReset: () => void }
export default function Investments({ view, controls, onChange, onReset }: Props) {
  const { currency, hidden } = useContext(DisplayContext)
  const [filtersOpen, setFiltersOpen] = useState(false)
  const filtersId = useId()
  const holdings = view === 'empty' ? [] : getHoldings(view === 'partial')
  const total = holdingsTotal(holdings)
  const selected = selectHoldings(holdings, controls)
  const missing = holdings.filter(item => item.value === null).length
  const stale = holdings.filter(item => item.stale).length
  const matchingMissing = selected.filter(item => item.value === null).length
  const subtotal = selected.length > 0 && matchingMissing === selected.length ? null : holdingsTotal(selected)
  const activeFilters = Object.entries(controls.filters).filter(([key, value]) => key === 'query' ? value.trim() : value)
  const extraFilterCount = ['market', 'currency', 'plan', 'status'].filter(key => controls.filters[key as keyof HoldingFilters]).length

  function filter(key: keyof HoldingFilters, value: string) { onChange({ ...controls, filters: { ...controls.filters, [key]: value } }) }
  function reset() { onChange({ ...controls, filters: { ...defaultFilters } }) }
  function sort(field: SortField) { onChange({ ...controls, sort: field, direction: controls.sort === field && controls.direction === 'desc' ? 'asc' : 'desc' }) }
  function filterLabel(key: string, value: string) {
    if (key === 'query') return `Search: ${value.trim()}`
    if (key === 'account') return accountName(value)
    if (key === 'type') return types.find(type => type.value === value)?.label ?? value
    if (key === 'status') return value === 'missing' ? 'Missing price' : value === 'stale' ? 'Stale holdings' : 'Complete snapshots'
    return value
  }
  function sortHeading(field: SortField, label: string, className: string) {
    const active = controls.sort === field
    const Icon = active ? controls.direction === 'asc' ? ArrowUp : ArrowDown : ArrowDownUp
    return <th scope="col" role="columnheader" className={className} aria-sort={active ? controls.direction === 'asc' ? 'ascending' : 'descending' : 'none'}>
      <button onClick={() => sort(field)} aria-label={`Sort by ${field === 'date' ? 'holdings date' : label.toLowerCase()}`}>{label}<Icon size={12} aria-hidden="true" /></button><span className="mobile-column-title">{label}</span>
    </th>
  }

  return <>
    <div className="page-heading"><div><span className="eyebrow">Your investments <span className="mobile-demo">· Sample data</span></span><h1 id="page-title" tabIndex={-1}>Every holding, in focus<span>.</span></h1><p>Across markets and accounts. One considered view.</p></div><div className="snapshot-label"><Clock3 size={14} aria-hidden="true" /><span>Sample snapshot<strong>{AS_OF}</strong></span></div></div>
    {view === 'loading' ? <section className="holdings-loading" aria-busy="true" aria-label="Loading holdings"><span className="sr-only" role="status">Loading sample holdings</span><div className="skeleton-panel"><div className="skeleton number" />{[0, 1, 2, 3].map(row => <div key={row} className="skeleton holding-skeleton-row" />)}</div></section>
      : view === 'empty' ? <section className="empty-state" aria-labelledby="holdings-empty-title"><div className="empty-art" aria-hidden="true"><div /><Layers3 size={39} /></div><span className="eyebrow">Room to grow</span><h2 id="holdings-empty-title">No investment holdings yet.</h2><p>This sample view has no investment accounts.<br />Load the fictional portfolio to explore the list.</p><button className="primary-button" onClick={() => { reset(); onReset() }}>Explore sample holdings</button></section>
        : <>
          <section className="summary-grid investment-summary" aria-label="Investment summary">
            <div className="summary-primary"><div className="summary-label"><span>{missing ? 'Known investment value' : 'Investment value'}</span><Wallet size={19} aria-hidden="true" /></div><p className="hero-amount"><Amount value={total} /></p><p className="summary-caption">{missing ? `Excludes ${missing} unpriced holding` : 'Current sample value · Excludes cash'}</p></div>
            <div className="summary-secondary"><div className="summary-label"><span>Holdings</span><Layers3 size={19} aria-hidden="true" /></div><p className="metric-amount">{holdings.length}</p><p className="summary-caption">{holdings.filter(item => item.instrument.type === 'stock').length} stocks · {holdings.filter(item => item.instrument.type === 'etf').length} ETFs · {holdings.filter(item => item.instrument.type === 'fund').length} funds</p></div>
            <div className="summary-secondary"><div className="summary-label"><span>Investment accounts</span><BarChart3 size={19} aria-hidden="true" /></div><p className="metric-amount">{new Set(holdings.map(item => item.accountId)).size}</p><p className="summary-caption">INDmoney · Advisor · UBS</p></div>
          </section>
          <div className={`investment-coverage ${missing || stale ? 'has-warning' : ''}`}><ShieldCheck size={16} aria-hidden="true" /><span>{missing || stale ? `${missing} unpriced · ${stale} stale. Totals include known values; stale holdings remain included.` : 'All holdings priced in this sample. Holdings and quote dates are shown separately.'}</span></div>
          <section className="panel holdings-panel" aria-labelledby="holdings-title">
            <div className="holdings-panel-title"><div><h2 id="holdings-title">Your holdings</h2><p>A closer look at what you own.</p></div><span className="quiet-badge">Fictional portfolio</span></div>
            <div className="holdings-toolbar">
              <label className="holdings-search"><Search size={17} aria-hidden="true" /><span className="sr-only">Search holdings</span><input type="search" placeholder="Search name, ticker or fund" maxLength={200} value={controls.filters.query} onChange={event => filter('query', event.target.value)} autoComplete="off" spellCheck={false} /></label>
              <label className="holding-select"><span>Account</span><select value={controls.filters.account} onChange={event => filter('account', event.target.value)}><option value="">All accounts</option>{investmentAccounts.map(account => <option value={account.id} key={account.id}>{accountName(account.id)}</option>)}</select></label>
              <button className={`filter-toggle ${filtersOpen || extraFilterCount ? 'selected' : ''}`} aria-expanded={filtersOpen} aria-controls={filtersId} onClick={() => setFiltersOpen(!filtersOpen)}><Filter size={15} aria-hidden="true" />Filters{extraFilterCount > 0 && <span>{extraFilterCount}</span>}</button>
            </div>
            <div className="holding-filter-grid" id={filtersId} hidden={!filtersOpen}>
              <label className="holding-select"><span>Market</span><select value={controls.filters.market} onChange={event => filter('market', event.target.value)}><option value="">All markets</option><option>India</option><option>US</option></select></label>
              <label className="holding-select"><span>Native currency</span><select value={controls.filters.currency} onChange={event => filter('currency', event.target.value)}><option value="">All currencies</option><option>INR</option><option>USD</option></select></label>
              <label className="holding-select"><span>Fund plan</span><select value={controls.filters.plan} onChange={event => filter('plan', event.target.value)}><option value="">All plans</option><option>Direct</option><option>Regular</option></select></label>
              <label className="holding-select"><span>Data status</span><select value={controls.filters.status} onChange={event => filter('status', event.target.value)}><option value="">All statuses</option><option value="complete">Complete snapshots</option><option value="missing">Missing price</option><option value="stale">Stale holdings</option></select></label>
              <p>Market is the instrument's listing or scheme market, not its underlying geographic exposure.</p>
            </div>
            <div className="holding-type-row"><div className="holding-types" role="group" aria-label="Instrument type">{types.map(type => <button key={type.value} aria-pressed={controls.filters.type === type.value} onClick={() => filter('type', type.value)}>{type.label}<span>{type.value ? holdings.filter(item => item.instrument.type === type.value).length : holdings.length}</span></button>)}</div>
              <label className="holding-sort"><span>Sort</span><select value={`${controls.sort}:${controls.direction}`} onChange={event => { const [field, direction] = event.target.value.split(':'); onChange({ ...controls, sort: field as SortField, direction: direction as 'asc' | 'desc' }) }}><option value="value:desc">Value: high to low</option><option value="value:asc">Value: low to high</option><option value="name:asc">Name: A to Z</option><option value="name:desc">Name: Z to A</option><option value="weight:desc">Weight: high to low</option><option value="weight:asc">Weight: low to high</option><option value="date:desc">Holdings date: newest</option><option value="date:asc">Holdings date: oldest</option></select></label>
            </div>
            {activeFilters.length > 0 && <div className="active-holding-filters" aria-label="Active filters">{activeFilters.map(([key, value]) => <button key={key} onClick={() => filter(key as keyof HoldingFilters, '')} aria-label={`Remove ${filterLabel(key, value)} filter`}>{filterLabel(key, value)}<X size={12} aria-hidden="true" /></button>)}<button className="clear-filters" onClick={reset}>Clear all</button></div>}
            <div className="holdings-result-bar"><span role="status" aria-live="polite" aria-atomic="true">Showing <strong>{selected.length}</strong> of {holdings.length} holdings{matchingMissing ? ` · ${matchingMissing} unpriced` : ''}</span><span>{matchingMissing ? 'Matching known value' : 'Matching value'} <strong><Amount value={subtotal} /></strong></span></div>
            {selected.length === 0 ? <div className="holdings-no-results"><Search size={28} aria-hidden="true" /><h3>No holdings match these filters.</h3><p>Try another name or clear your filters to see the full portfolio.</p><button className="text-button" onClick={reset}>Clear all filters</button></div> :
              <table className="holdings-table" role="table"><caption className="sr-only">Investment holdings. Values in {currency}; native quotes keep their original currency. Weights use all valued investments, excluding cash.</caption><thead role="rowgroup"><tr role="row">
                {sortHeading('name', 'Instrument', 'holding-name-cell')}<th scope="col" role="columnheader" className="holding-account-cell">Account</th><th scope="col" role="columnheader" className="holding-units-cell">Units</th><th scope="col" role="columnheader" className="holding-quote-cell">Price / NAV</th>{sortHeading('value', `Value (${currency})`, 'holding-value-cell')}{sortHeading('weight', 'Weight', 'holding-weight-cell')}{sortHeading('date', 'Source dates', 'holding-date-cell')}
              </tr></thead><tbody role="rowgroup">{selected.map(holding => {
                const weight = holdingWeight(holding, total)
                return <tr role="row" key={holding.id}>
                  <th role="rowheader" scope="row" className="holding-name-cell"><HoldingIdentity holding={holding} /></th>
                  <td role="cell" className="holding-account-cell"><span>{accountName(holding.accountId)}</span>{holding.employeePlan && <small className="espp-label">{holding.employeePlan}</small>}{holding.folio && <small>{holding.folio}</small>}</td>
                  <td role="cell" className="holding-units-cell"><span className="mobile-cell-label" aria-hidden="true">Units</span><PrivateValue><span className="holding-number">{formatFixed(holding.units, UNIT_SCALE)}</span></PrivateValue></td>
                  <td role="cell" className="holding-quote-cell"><span className="mobile-cell-label" aria-hidden="true">{holding.instrument.type === 'fund' ? 'NAV' : 'Price'}</span><PrivateValue>{holding.quote ? <span className="holding-number">{holding.instrument.currency === 'INR' ? '₹' : '$'}{formatFixed(holding.quote.amount, QUOTE_SCALE, 2)}</span> : <span aria-label="Price unavailable">—</span>}</PrivateValue><small>{holding.instrument.currency} · native</small></td>
                  <td role="cell" className="holding-value-cell"><span className="mobile-cell-label" aria-hidden="true">Value · {currency}</span><Amount value={holding.value ? convert(holding.value, 'INR') : null} />{holding.value === null && <small>Excluded from total</small>}</td>
                  <td role="cell" className="holding-weight-cell"><span className="mobile-cell-label" aria-hidden="true">Portfolio weight</span><span>{weight === null ? '—' : `${weight.toFixed(1)}%`}</span><div className="weight-track" aria-hidden="true"><span style={{ width: `${weight ?? 0}%` }} /></div></td>
                  <td role="cell" className="holding-date-cell"><Freshness holding={holding} /></td>
                </tr>
              })}</tbody></table>}
            <div className="holdings-footnote"><ShieldCheck size={14} aria-hidden="true" /><p>Weights use {missing ? 'known' : 'all valued'} investments, excluding cash, and stay fixed when you filter. {hidden ? 'Amounts, units and quotes are hidden.' : 'Native quotes retain their currency. Rounded reporting values may differ from the total by a minor unit.'} All records and prices are fictional.</p></div>
          </section>
        </>}
  </>
}
