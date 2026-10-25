import { describe, expect, it } from 'vitest'
import { cardActivity, cardCurrent, cardStatements, getCardActivity, reconcileCardStatement } from './credit-cards'

describe('fabricated credit-card evidence', () => {
  it('reconciles the complete supplied statement using posted debit and credit roles once', () => {
    const result = reconcileCardStatement(cardStatements[0]!, cardActivity)
    expect(result?.minor).toBe(1500000n)
    expect(cardStatements[0]!.closing.minor).toBe(result?.minor)
    expect(cardActivity.filter(item => item.statement === 'oct')).toHaveLength(7)
  })
  it('keeps pending, post-statement payments and ambiguous instalments out of statement arithmetic', () => {
    const period = cardActivity.filter(item => item.statement === 'oct')
    expect(reconcileCardStatement(cardStatements[0]!, period)).toEqual(reconcileCardStatement(cardStatements[0]!, cardActivity))
    expect(cardActivity.filter(item => item.kind === 'instalment').every(item => item.effect === 'unresolved')).toBe(true)
    expect(cardActivity.find(item => !item.posted)?.effect).toBe('unresolved')
  })
  it('does not fill missing opening balances, current fields or incomplete coverage with zero', () => {
    expect(reconcileCardStatement(cardStatements[1]!, cardActivity)).toBeNull()
    expect(reconcileCardStatement(cardStatements[0]!, getCardActivity(true), true)).toBeNull()
    expect(cardStatements[1]!.minimum).toBeNull()
    expect(cardCurrent.available).toBeNull()
    expect(cardCurrent.unbilled).toBeNull()
    expect(cardCurrent.outstanding).not.toEqual(cardStatements[0]!.due)
  })
  it('returns a new selection without mutating supplied evidence', () => {
    const selected = getCardActivity(true)
    expect(selected).toHaveLength(cardActivity.length - 1)
    selected.pop()
    expect(cardActivity).toHaveLength(12)
    expect(getCardActivity()).toHaveLength(12)
  })
})
