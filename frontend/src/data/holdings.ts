import { convert, divideRounded, parseFixed, sum } from './money'
import type { Currency, Money } from './money'

export const UNIT_SCALE = 8
export const QUOTE_SCALE = 6
export type InstrumentType = 'stock' | 'etf' | 'fund'
export type Market = 'India' | 'US'
export type HoldingStatus = 'complete' | 'missing' | 'stale'
export interface Instrument {
  id: string; name: string; symbol: string; type: InstrumentType; market: Market; currency: Currency
  plan?: 'Direct' | 'Regular'; option?: 'Growth' | 'Distribution'
}
export interface Quote { amount: bigint; date: string }
export interface Holding {
  id: string; instrument: Instrument; accountId: string; folio?: string; employeePlan?: 'ESPP'
  units: bigint; holdingsDate: string; quote: Quote | null; stale: boolean; value: Money | null
}

// Names identify illustrative instruments; units, quotes, dates and values are all fabricated.
const instruments: readonly Instrument[] = [
  { id: 'reliance', name: 'Reliance Industries', symbol: 'RELIANCE', type: 'stock', market: 'India', currency: 'INR' },
  { id: 'hdfc', name: 'HDFC Bank', symbol: 'HDFCBANK', type: 'stock', market: 'India', currency: 'INR' },
  { id: 'infosys', name: 'Infosys', symbol: 'INFY', type: 'stock', market: 'India', currency: 'INR' },
  { id: 'india-etf', name: 'India Nifty 50 ETF', symbol: 'IND50', type: 'etf', market: 'India', currency: 'INR' },
  { id: 'apple', name: 'Apple', symbol: 'AAPL', type: 'stock', market: 'US', currency: 'USD' },
  { id: 'microsoft', name: 'Microsoft', symbol: 'MSFT', type: 'stock', market: 'US', currency: 'USD' },
  { id: 'us-total', name: 'US Total Market ETF', symbol: 'USTM', type: 'etf', market: 'US', currency: 'USD' },
  { id: 'us-tech', name: 'US Technology ETF', symbol: 'USTECH', type: 'etf', market: 'US', currency: 'USD' },
  { id: 'accenture', name: 'Accenture', symbol: 'ACN', type: 'stock', market: 'US', currency: 'USD' },
  { id: 'cedar-direct', name: 'Cedar Flexi Cap Fund', symbol: 'CEDAR-D', type: 'fund', market: 'India', currency: 'INR', plan: 'Direct', option: 'Growth' },
  { id: 'northstar-direct', name: 'Northstar Nifty 50 Index Fund', symbol: 'NORTH-D', type: 'fund', market: 'India', currency: 'INR', plan: 'Direct', option: 'Growth' },
  { id: 'harbor-direct', name: 'Harbor Balanced Advantage Fund', symbol: 'HARBOR-D', type: 'fund', market: 'India', currency: 'INR', plan: 'Direct', option: 'Distribution' },
  { id: 'northstar-regular', name: 'Northstar Nifty 50 Index Fund', symbol: 'NORTH-R', type: 'fund', market: 'India', currency: 'INR', plan: 'Regular', option: 'Growth' },
]

const prices: Record<string, string> = {
  reliance: '2800', hdfc: '1650', infosys: '1600', 'india-etf': '218.65', apple: '210', microsoft: '430',
  'us-total': '600', 'us-tech': '500', accenture: '300', 'cedar-direct': '84', 'northstar-direct': '155',
  'harbor-direct': '47', 'northstar-regular': '85',
}
interface Snapshot { id: string; instrumentId: string; accountId: string; units: string; folio?: string; employeePlan?: 'ESPP' }
const snapshots: readonly Snapshot[] = [
  { id: 'h01', instrumentId: 'reliance', accountId: 'ind-in', units: '150' },
  { id: 'h02', instrumentId: 'hdfc', accountId: 'ind-in', units: '200' },
  { id: 'h03', instrumentId: 'infosys', accountId: 'ind-in', units: '175' },
  { id: 'h04', instrumentId: 'india-etf', accountId: 'ind-in', units: '1000' },
  { id: 'h05', instrumentId: 'apple', accountId: 'ind-us', units: '20' },
  { id: 'h06', instrumentId: 'microsoft', accountId: 'ind-us', units: '8' },
  { id: 'h07', instrumentId: 'us-total', accountId: 'ind-us', units: '8.25' },
  { id: 'h08', instrumentId: 'us-tech', accountId: 'ind-us', units: '9.7' },
  { id: 'h09', instrumentId: 'accenture', accountId: 'ind-us', units: '4' },
  { id: 'h10', instrumentId: 'cedar-direct', accountId: 'ind-in', units: '5000', folio: 'Sample folio A' },
  { id: 'h11', instrumentId: 'northstar-direct', accountId: 'ind-in', units: '2000', folio: 'Sample folio B' },
  { id: 'h12', instrumentId: 'harbor-direct', accountId: 'ind-in', units: '5000', folio: 'Sample folio C' },
  { id: 'h13', instrumentId: 'northstar-regular', accountId: 'advisor', units: '5000', folio: 'Sample folio D' },
  { id: 'h14', instrumentId: 'accenture', accountId: 'ubs', units: '24', employeePlan: 'ESPP' },
]

export function valueHolding(units: bigint, quote: bigint, currency: Currency): Money {
  if (units < 0n || quote < 0n) throw new Error('Long holdings require nonnegative units and quotes')
  return { minor: divideRounded(units * quote, 10n ** BigInt(UNIT_SCALE + QUOTE_SCALE - 2)), currency }
}

export function isHoldingId(id: string): boolean { return snapshots.some(snapshot => snapshot.id === id) }

export function getHoldings(partial = false): Holding[] {
  return snapshots.map(snapshot => {
    const instrument = instruments.find(item => item.id === snapshot.instrumentId)!
    const units = parseFixed(snapshot.units, UNIT_SCALE)
    const stale = partial && snapshot.accountId === 'ubs'
    const holdingsDate = stale ? '2026-10-17T03:30:00Z' : snapshot.accountId === 'advisor' ? '2026-10-18T04:30:00Z'
      : instrument.market === 'US' ? '2026-10-20T03:30:00Z' : '2026-10-20T12:00:00Z'
    const quote = partial && snapshot.id === 'h13' ? null : {
      amount: parseFixed(prices[instrument.id]!, QUOTE_SCALE),
      date: instrument.market === 'US' ? '2026-10-19T20:00:00Z' : '2026-10-20T12:30:00Z',
    }
    return { ...snapshot, instrument: { ...instrument }, units, holdingsDate, quote, stale, value: quote ? valueHolding(units, quote.amount, instrument.currency) : null }
  })
}

export function holdingStatus(holding: Holding): HoldingStatus { return holding.quote === null ? 'missing' : holding.stale ? 'stale' : 'complete' }
export function holdingsTotal(holdings: readonly Holding[]): Money { return sum(holdings.flatMap(item => item.value ? [item.value] : [])) }
export function holdingWeight(holding: Holding, total: Money): number | null {
  return holding.value === null || total.minor === 0n ? null : Number(convert(holding.value, 'INR').minor) / Number(total.minor) * 100
}

export interface HoldingFilters {
  query: string; type: InstrumentType | ''; market: Market | ''; account: string; currency: Currency | ''
  plan: 'Direct' | 'Regular' | ''; status: HoldingStatus | ''
}
export type SortField = 'name' | 'value' | 'weight' | 'date'
export interface HoldingsControls { filters: HoldingFilters; sort: SortField; direction: 'asc' | 'desc' }
export const defaultFilters: HoldingFilters = { query: '', type: '', market: '', account: '', currency: '', plan: '', status: '' }
export const defaultControls: HoldingsControls = { filters: defaultFilters, sort: 'value', direction: 'desc' }

export function selectHoldings(holdings: readonly Holding[], { filters, sort, direction }: HoldingsControls): Holding[] {
  const query = filters.query.trim().toLocaleLowerCase('en-US')
  const selected = holdings.filter(item => {
    const instrument = item.instrument
    return (!query || `${instrument.name} ${instrument.symbol}`.toLocaleLowerCase('en-US').includes(query))
      && (!filters.type || instrument.type === filters.type) && (!filters.market || instrument.market === filters.market)
      && (!filters.account || item.accountId === filters.account) && (!filters.currency || instrument.currency === filters.currency)
      && (!filters.plan || instrument.plan === filters.plan) && (!filters.status || holdingStatus(item) === filters.status)
  })
  return selected.sort((a, b) => {
    let order = 0
    if (sort === 'value' || sort === 'weight') {
      if (a.value === null || b.value === null) return a.value === b.value ? a.id.localeCompare(b.id) : a.value === null ? 1 : -1
      const left = convert(a.value, 'INR').minor
      const right = convert(b.value, 'INR').minor
      order = left < right ? -1 : left > right ? 1 : 0
    } else if (sort === 'name') order = a.instrument.name.localeCompare(b.instrument.name, 'en')
    else order = Date.parse(a.holdingsDate) - Date.parse(b.holdingsDate)
    return (direction === 'asc' ? order : -order) || a.id.localeCompare(b.id)
  })
}
