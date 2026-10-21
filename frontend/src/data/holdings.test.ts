import { describe, expect, it } from 'vitest'
import { convert, formatFixed, money, parseFixed } from './money'
import { defaultControls, defaultFilters, getHoldings, holdingStatus, holdingsTotal, holdingWeight, selectHoldings, valueHolding } from './holdings'
import type { HoldingFilters } from './holdings'
import { getPositions, getSummary } from './portfolio'

describe('holding valuation and identity', () => {
  it('derives both screens from individual holdings while preserving the original totals', () => {
    const holdings = getHoldings()
    expect(holdings).toHaveLength(14)
    expect(new Set(holdings.map(item => item.id)).size).toBe(14)
    expect(holdingsTotal(holdings)).toEqual(money('4796290'))
    expect(holdingsTotal(getHoldings(true))).toEqual(money('4371290'))
    for (const partial of [false, true]) {
      const positions = getPositions(partial)
      expect(getSummary(positions).invested).toEqual(holdingsTotal(getHoldings(partial)))
      expect(positions.filter(position => position.category !== 'cash').map(position => position.value)).toEqual(getHoldings(partial).map(item => item.value))
      expect(getSummary(positions).cash).toEqual(money('289790'))
    }
  })
  it('keeps shared securities and fund plan identities separate', () => {
    const holdings = getHoldings()
    const accenture = holdings.filter(item => item.instrument.symbol === 'ACN')
    expect(accenture.map(item => item.accountId)).toEqual(['ind-us', 'ubs'])
    expect(accenture[1]?.employeePlan).toBe('ESPP')
    const funds = holdings.filter(item => item.instrument.name === 'Northstar Nifty 50 Index Fund')
    expect(new Set(funds.map(item => item.instrument.id)).size).toBe(2)
    expect(funds.map(item => item.instrument.plan)).toEqual(['Direct', 'Regular'])
    expect(new Set(funds.map(item => item.folio)).size).toBe(2)
  })
  it('values fractional units exactly and rounds native minor units before FX', () => {
    expect(valueHolding(parseFixed('8.25', 8), parseFixed('600', 6), 'USD')).toEqual(money('4950', 'USD'))
    expect(valueHolding(parseFixed('0.33333333', 8), parseFixed('3', 6), 'USD')).toEqual(money('1', 'USD'))
    expect(valueHolding(parseFixed('1', 8), parseFixed('0.004999', 6), 'INR')).toEqual(money('0'))
    expect(valueHolding(parseFixed('1', 8), parseFixed('0.005', 6), 'INR')).toEqual(money('0.01'))
    const native = valueHolding(parseFixed('1', 8), parseFixed('1.005', 6), 'USD')
    expect(native).toEqual(money('1.01', 'USD'))
    expect(convert(native, 'INR')).toEqual(money('84.34'))
    expect(valueHolding(0n, 0n, 'INR')).toEqual(money('0'))
    expect(() => valueHolding(-1n, 1n, 'INR')).toThrow()
    expect(() => parseFixed('1.000000001', 8)).toThrow()
    expect(() => parseFixed('1e3', 6)).toThrow()
  })
  it('formats precise units and quotes without first converting them to floating point', () => {
    expect(formatFixed(parseFixed('9007199254740993.12345678', 8), 8)).toBe('9,007,199,254,740,993.12345678')
    expect(formatFixed(parseFixed('47.012345', 6), 6, 2)).toBe('47.012345')
    expect(formatFixed(parseFixed('600', 6), 6, 2)).toBe('600.00')
  })
  it('keeps unknown valuations and separate stale holdings/quote dates explicit', () => {
    const holdings = getHoldings(true)
    const missing = holdings.find(item => item.accountId === 'advisor')!
    expect(missing.quote).toBeNull()
    expect(missing.value).toBeNull()
    expect(missing.units).toBeGreaterThan(0n)
    expect(holdingWeight(missing, holdingsTotal(holdings))).toBeNull()
    const stale = holdings.find(item => item.accountId === 'ubs')!
    expect(holdingStatus(stale)).toBe('stale')
    expect(Date.parse(stale.holdingsDate)).toBeLessThan(Date.parse(stale.quote!.date))
    expect(stale.value).toEqual(money('7200', 'USD'))
  })
})

describe('holdings search, filters and ordering', () => {
  const select = (filters: Partial<HoldingFilters>, partial = false) => selectHoldings(getHoldings(partial), { ...defaultControls, filters: { ...defaultFilters, ...filters } })
  it('combines filters and performs trimmed case-insensitive literal search', () => {
    expect(select({ query: ' acN ', type: 'stock', market: 'US', currency: 'USD', account: 'ubs', status: 'stale' }, true).map(item => item.id)).toEqual(['h14'])
    expect(select({ query: 'northstar', type: 'fund', plan: 'Direct' }).map(item => item.id)).toEqual(['h11'])
    expect(select({ query: ' [.* ' })).toEqual([])
    expect(select({ type: 'stock', plan: 'Direct' })).toEqual([])
    expect(select({ query: '   ' })).toHaveLength(14)
    expect(select({ status: 'missing' }, true).map(item => item.id)).toEqual(['h13'])
  })
  it('uses explicit market metadata, independently from currency', () => {
    const item = getHoldings()[0]!
    const changed = { ...item, instrument: { ...item.instrument, currency: 'USD' as const } }
    expect(selectHoldings([changed], { ...defaultControls, filters: { ...defaultFilters, market: 'India', currency: 'USD' } })).toHaveLength(1)
  })
  it('sorts numeric valuations in either direction with unknown values last', () => {
    for (const direction of ['asc', 'desc'] as const) {
      const result = selectHoldings(getHoldings(true), { ...defaultControls, direction })
      expect(result.at(-1)?.id).toBe('h13')
      const values = result.slice(0, -1).map(item => convert(item.value!, 'INR').minor)
      for (let i = 1; i < values.length; i++) expect(direction === 'asc' ? values[i]! >= values[i - 1]! : values[i]! <= values[i - 1]!).toBe(true)
    }
  })
  it('uses stable identifiers for ties and correctly orders source timestamps', () => {
    const holdings = getHoldings(true)
    for (const direction of ['asc', 'desc'] as const) {
      expect(selectHoldings(holdings, { filters: { ...defaultFilters, query: 'ACN' }, sort: 'name', direction }).map(item => item.id)).toEqual(['h09', 'h14'])
    }
    expect(selectHoldings(holdings, { ...defaultControls, sort: 'date', direction: 'asc' })[0]?.id).toBe('h14')
    expect(selectHoldings(holdings, { ...defaultControls, sort: 'date', direction: 'desc' }).at(-1)?.id).toBe('h14')
  })
  it('uses the full known investment denominator and does not mutate source records', () => {
    const holdings = getHoldings()
    const original = holdings.map(item => item.id)
    const total = holdingsTotal(holdings)
    const selected = selectHoldings(holdings, { ...defaultControls, filters: { ...defaultFilters, account: 'ubs' } })
    expect(holdingWeight(selected[0]!, total)).toBeCloseTo(12.5346903627597)
    expect(holdingWeight(selected[0]!, total)).not.toBe(100)
    expect(holdings.map(item => item.id)).toEqual(original)
    expect(getHoldings().find(item => item.accountId === 'advisor')?.value).not.toBeNull()
  })
})
