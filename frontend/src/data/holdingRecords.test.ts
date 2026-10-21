import { describe, expect, it } from 'vitest'
import { getEmployeeLots, getHoldingActivity } from './holdingRecords'
import { getHoldings, valueHolding } from './holdings'
import { money, parseFixed } from './money'

describe('holding source records', () => {
  it('reconciles fractional open lots to the UBS position with explicit purchase amounts and fees', () => {
    const lots = getEmployeeLots('h14')
    expect(lots).toHaveLength(3)
    expect(lots.reduce((total, lot) => total + lot.remainingUnits, 0n)).toBe(parseFixed('24', 8))
    for (const partial of [false, true]) expect(lots.reduce((total, lot) => total + lot.remainingUnits, 0n)).toBe(getHoldings(partial).find(item => item.id === 'h14')?.units)
    expect(lots.map(lot => lot.purchaseAmount)).toEqual([money('1964', 'USD'), money('1705.60', 'USD'), money('2629.60', 'USD')])
    for (const lot of lots) expect(valueHolding(lot.remainingUnits, lot.purchasePrice, 'USD')).toEqual(lot.purchaseAmount)
    expect(lots.map(lot => lot.fee)).toEqual([money('0', 'USD'), null, money('1.25', 'USD')])
    expect(getEmployeeLots('h09')).toEqual([])
  })
  it('scopes activity by holding identity and preserves original amounts independently of market value', () => {
    const events = getHoldingActivity('h14')
    expect(events.every(event => event.holdingId === 'h14' && event.amount.currency === 'USD')).toBe(true)
    expect(events.filter(event => event.kind === 'purchase').reduce((total, event) => total + event.units!, 0n)).toBe(parseFixed('24', 8))
    expect(events.filter(event => event.kind === 'fee').map(event => event.amount)).toEqual([money('1.25', 'USD')])
    expect(getHoldingActivity('h09').map(event => event.amount)).toEqual([money('1120', 'USD')])
    expect(getHoldingActivity('h13')[0]?.amount).toEqual(money('81000'))
    expect(getHoldingActivity('h02')).toEqual([])
    expect(getHoldingActivity('unknown')).toEqual([])
    for (let index = 1; index < events.length; index++) expect(events[index - 1]!.date >= events[index]!.date).toBe(true)
  })
  it('returns independent records without changing valuation snapshots', () => {
    const before = getHoldings()
    const lot = getEmployeeLots('h14')[0]!
    lot.purchaseAmount = money('1', 'USD')
    const event = getHoldingActivity('h14')[0]!
    event.label = 'Changed locally'
    expect(getEmployeeLots('h14')[0]?.purchaseAmount).toEqual(money('1964', 'USD'))
    expect(getHoldingActivity('h14')[0]?.label).not.toBe('Changed locally')
    expect(getHoldings()).toEqual(before)
  })
})
