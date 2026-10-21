import { money, parseFixed } from './money'
import type { Money } from './money'
import { UNIT_SCALE, QUOTE_SCALE } from './holdings'

export interface HoldingActivity {
  id: string; holdingId: string; date: string; kind: 'purchase' | 'dividend' | 'fee'
  label: string; amount: Money; units?: bigint
}
export interface EmployeeLot {
  id: string; holdingId: string; date: string; remainingUnits: bigint; purchasePrice: bigint
  purchaseAmount: Money; fee: Money | null
}
const units = (value: string) => parseFixed(value, UNIT_SCALE)

// Illustrative source records, independent of current quotes and reporting FX.
const lots: readonly EmployeeLot[] = [
  { id: 'lot-a', holdingId: 'h14', date: '2025-11-15', remainingUnits: units('8'), purchasePrice: parseFixed('245.50', QUOTE_SCALE), purchaseAmount: money('1964', 'USD'), fee: money('0', 'USD') },
  { id: 'lot-b', holdingId: 'h14', date: '2026-05-15', remainingUnits: units('6.5'), purchasePrice: parseFixed('262.40', QUOTE_SCALE), purchaseAmount: money('1705.60', 'USD'), fee: null },
  { id: 'lot-c', holdingId: 'h14', date: '2026-08-15', remainingUnits: units('9.5'), purchasePrice: parseFixed('276.80', QUOTE_SCALE), purchaseAmount: money('2629.60', 'USD'), fee: money('1.25', 'USD') },
]

const activity: readonly HoldingActivity[] = [
  { id: 'event-01', holdingId: 'h01', date: '2026-08-12', kind: 'purchase', label: 'Share purchase', amount: money('132500'), units: units('50') },
  { id: 'event-02', holdingId: 'h05', date: '2026-08-14', kind: 'dividend', label: 'Cash dividend', amount: money('5.20', 'USD') },
  { id: 'event-03', holdingId: 'h05', date: '2026-04-09', kind: 'purchase', label: 'Share purchase', amount: money('950', 'USD'), units: units('5') },
  { id: 'event-04', holdingId: 'h07', date: '2026-06-11', kind: 'purchase', label: 'ETF purchase', amount: money('1293.75', 'USD'), units: units('2.25') },
  { id: 'event-05', holdingId: 'h09', date: '2026-07-21', kind: 'purchase', label: 'Share purchase', amount: money('1120', 'USD'), units: units('4') },
  { id: 'event-06', holdingId: 'h10', date: '2026-09-05', kind: 'purchase', label: 'Fund subscription', amount: money('40000'), units: units('500') },
  { id: 'event-07', holdingId: 'h12', date: '2026-09-18', kind: 'dividend', label: 'Cash distribution', amount: money('1250') },
  { id: 'event-08', holdingId: 'h13', date: '2026-07-08', kind: 'purchase', label: 'Fund subscription', amount: money('81000'), units: units('1000') },
  ...lots.map(lot => ({ id: `event-${lot.id}`, holdingId: lot.holdingId, date: lot.date, kind: 'purchase' as const, label: 'ESPP purchase', amount: lot.purchaseAmount, units: lot.remainingUnits })),
  { id: 'event-09', holdingId: 'h14', date: '2026-08-15', kind: 'fee', label: 'Purchase fee', amount: money('1.25', 'USD') },
  { id: 'event-10', holdingId: 'h14', date: '2026-08-21', kind: 'dividend', label: 'Cash dividend', amount: money('30.96', 'USD') },
]

export function getHoldingActivity(holdingId: string): HoldingActivity[] {
  return activity.filter(item => item.holdingId === holdingId)
    .map(item => ({ ...item, amount: { ...item.amount } }))
    .sort((a, b) => b.date.localeCompare(a.date) || a.id.localeCompare(b.id))
}
export function getEmployeeLots(holdingId: string): EmployeeLot[] {
  return lots.filter(item => item.holdingId === holdingId).map(item => ({ ...item, purchaseAmount: { ...item.purchaseAmount }, fee: item.fee ? { ...item.fee } : null }))
}
