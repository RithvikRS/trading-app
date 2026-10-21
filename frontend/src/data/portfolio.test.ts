import { describe, expect, it } from 'vitest'
import { accounts, activity, assetClasses, convert, formatMoney, getAccountValue, getPositions, getSummary, history, money, spendingTotal, sum } from './portfolio'
import { convertScaled } from './money'

describe('fictional portfolio accounting', () => {
  it('reconciles assets, allocation and account totals without counting cash twice', () => {
    const positions = getPositions()
    const summary = getSummary(positions)
    expect(summary.invested).toEqual(money('4796290'))
    expect(summary.cash).toEqual(money('289790'))
    expect(summary.total).toEqual(money('5086080'))
    expect(summary.missing).toBe(0)
    expect(sum(accounts.map(account => getAccountValue(positions, account.id)!))).toEqual(summary.total)
    expect(sum(assetClasses.map(category => sum(positions.filter(item => item.category === category.id).map(item => item.value!))))).toEqual(summary.total)
    expect(history.at(-1)?.value).toEqual(summary.total)
  })

  it('keeps an unpriced holding unknown and excludes it from the known subtotal', () => {
    const positions = getPositions(true)
    expect(getAccountValue(positions, 'advisor')).toBeNull()
    expect(getSummary(positions)).toEqual({ total: money('4661080'), invested: money('4371290'), cash: money('289790'), missing: 1 })
    expect(getSummary(getPositions()).total).toEqual(money('5086080'))
  })

  it('does not count matched transfers or purchases as spending', () => {
    expect(spendingTotal(activity)).toEqual(money('2450'))
    expect(spendingTotal(activity.filter(item => item.kind === 'transfer'))).toEqual(money('0'))
  })
})

describe('minor-unit money and fictional FX', () => {
  it.each(['0.001', 'NaN', '1e5', '', '1,000', 'Infinity'])('rejects ambiguous or overprecise input %s', value => {
    expect(() => money(value)).toThrow()
  })
  it('preserves cents, including negative values and addition', () => {
    expect(money('-0.01').minor).toBe(-1n)
    expect(sum([money('0.10'), money('0.20')])).toEqual(money('0.30'))
    expect(sum([money('-1.50'), money('1.49')])).toEqual(money('-0.01'))
  })
  it('uses the dated sample rate with half-away-from-zero rounding', () => {
    expect(convert(money('1', 'USD'), 'INR')).toEqual(money('83.50'))
    expect(convert(money('0.01', 'USD'), 'INR')).toEqual(money('0.84'))
    expect(convert(money('-0.01', 'USD'), 'INR')).toEqual(money('-0.84'))
    expect(convert(money('83.50'), 'USD')).toEqual(money('1', 'USD'))
    expect(convert(money('5086080'), 'USD')).toEqual(money('60911.14', 'USD'))
  })
  it('formats the correct reporting currency and rejects unsafe display magnitudes', () => {
    expect(formatMoney(money('1248650'))).toBe('₹12,48,650')
    expect(formatMoney(money('42.50', 'USD'))).toBe('$42.50')
    expect(() => formatMoney({ minor: BigInt(Number.MAX_SAFE_INTEGER) + 1n, currency: 'INR' })).toThrow()
  })
  it('converts quotes at their six-decimal scale without rounding them to cents first', () => {
    expect(convertScaled(2750000000n, 'INR', 'USD')).toBe(32934132n)
    expect(convertScaled(1234567n, 'USD', 'INR')).toBe(103086345n)
    expect(convertScaled(-1n, 'USD', 'INR')).toBe(-84n)
    expect(convertScaled(0n, 'INR', 'USD')).toBe(0n)
    expect(convertScaled(1234567n, 'USD', 'USD')).toBe(1234567n)
  })
})
