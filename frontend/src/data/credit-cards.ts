import { money } from './money'
import type { Money } from './money'

export type CardKind = 'purchase' | 'payment' | 'refund' | 'fee' | 'interest' | 'tax' | 'instalment'
export interface CardActivity {
  id: string; date: string; posted: string | null; statement: string | null
  description: string; narration: string; kind: CardKind
  amount: Money; effect: 'increases' | 'reduces' | 'unresolved'
}
export interface CardStatement {
  id: string; label: string; from: string; to: string; date: string; dueDate: string
  opening: Money | null; closing: Money; due: Money; minimum: Money | null; complete: boolean
}
export const cardStatements: readonly CardStatement[] = [
  { id: 'oct', label: 'October 2026', from: '2026-09-16', to: '2026-10-15', date: '2026-10-15', dueDate: '2026-11-04', opening: money('10000'), closing: money('15000'), due: money('15000'), minimum: money('750'), complete: true },
  { id: 'sep', label: 'September 2026', from: '2026-08-16', to: '2026-09-15', date: '2026-09-15', dueDate: '2026-10-05', opening: null, closing: money('10000'), due: money('10000'), minimum: null, complete: false },
]
// Deliberately fabricated examples; no HDFC document layout or field contract is implied.
export const cardActivity: readonly CardActivity[] = [
  { id: 'c12', date: '2026-10-20', posted: null, statement: null, description: 'Maple hotel authorization', narration: 'Fictional hold for INR 1800; final posting has not been supplied.', kind: 'purchase', amount: money('1800'), effect: 'unresolved' },
  { id: 'c11', date: '2026-10-19', posted: '2026-10-20', statement: null, description: 'Instalment principal label', narration: 'Fictional instalment label INR 700; relationship to the original purchase and conversion is unknown.', kind: 'instalment', amount: money('700'), effect: 'unresolved' },
  { id: 'c10', date: '2026-10-19', posted: '2026-10-19', statement: null, description: 'Purchase conversion label', narration: 'Fictional conversion label INR 3500. This may refer to a purchase already recorded; do not count it again.', kind: 'instalment', amount: money('3500'), effect: 'unresolved' },
  { id: 'c09', date: '2026-10-18', posted: '2026-10-18', statement: null, description: 'Payment received', narration: 'Fictional credit INR 5000. Bank counterpart and allocation to statements have not been supplied.', kind: 'payment', amount: money('5000'), effect: 'reduces' },
  { id: 'c08', date: '2026-10-15', posted: '2026-10-15', statement: 'oct', description: 'Statement tax', narration: 'Fictional tax INR 90. No tax computation or recommendation is provided.', kind: 'tax', amount: money('90'), effect: 'increases' },
  { id: 'c07', date: '2026-10-15', posted: '2026-10-15', statement: 'oct', description: 'Statement interest', narration: 'Fictional source charge INR 410, not an interest forecast.', kind: 'interest', amount: money('410'), effect: 'increases' },
  { id: 'c06', date: '2026-10-14', posted: '2026-10-15', statement: 'oct', description: 'Account fee', narration: 'Fictional source fee INR 500.', kind: 'fee', amount: money('500'), effect: 'increases' },
  { id: 'c05', date: '2026-10-10', posted: '2026-10-12', statement: 'oct', description: 'Willow store refund', narration: 'Fictional credit INR 2000. Original purchase is outside the supplied history; no automatic link is made.', kind: 'refund', amount: money('2000'), effect: 'reduces' },
  { id: 'c04', date: '2026-10-06', posted: '2026-10-07', statement: 'oct', description: 'Sample bank payment', narration: 'Fictional credit INR 6000. Unmatched settlement; not another expense or income.', kind: 'payment', amount: money('6000'), effect: 'reduces' },
  { id: 'c03', date: '2026-10-02', posted: '2026-10-03', statement: 'oct', description: 'Cedar home supplies', narration: 'Fictional primary-card purchase INR 3500.', kind: 'purchase', amount: money('3500'), effect: 'increases' },
  { id: 'c02', date: '2026-09-23', posted: '2026-09-24', statement: 'oct', description: 'Birch travel booking', narration: 'Fictional add-on purchase INR 8500; included in the same billing account once.', kind: 'purchase', amount: money('8500'), effect: 'increases' },
  { id: 'c01', date: '2026-09-05', posted: '2026-09-06', statement: 'sep', description: 'Earlier refund', narration: 'Fictional credit INR 500. Other rows for this period were not supplied.', kind: 'refund', amount: money('500'), effect: 'reduces' },
]
export const cardCurrent = { asOf: '20 Oct 2026, 10:00 IST', outstanding: money('12400'), unbilled: null, available: null, limit: money('100000') }
export const cardKinds: Record<CardKind, string> = { purchase: 'Purchase', payment: 'Payment', refund: 'Refund', fee: 'Fee', interest: 'Interest', tax: 'Tax', instalment: 'Instalment · Unresolved' }
export function getCardActivity(partial = false) { return cardActivity.filter(row => !partial || row.id !== 'c03') }
export function reconcileCardStatement(statement: CardStatement, rows: readonly CardActivity[], incomplete = false): Money | null {
  if (incomplete || !statement.complete || !statement.opening) return null
  const period = rows.filter(row => row.statement === statement.id)
  if (period.some(row => !row.posted || row.effect === 'unresolved' || row.amount.currency !== statement.closing.currency)) return null
  return { currency: statement.closing.currency, minor: statement.opening.minor + period.reduce((total, row) => total + (row.effect === 'reduces' ? -row.amount.minor : row.amount.minor), 0n) }
}
