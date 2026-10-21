import { money, sum } from './money'
import type { Money } from './money'
import { getHoldings } from './holdings'
export { money, sum, convert, formatMoney, axisLabel } from './money'
export type { Currency, Money } from './money'
export type DemoState = 'populated' | 'loading' | 'empty' | 'partial' | 'error'
export type AssetClass = 'india' | 'us' | 'funds' | 'cash'

export const AS_OF = '20 Oct 2026, 18:00 IST'
export const FX_DATE = '20 Oct 2026'

export interface Account {
  id: string
  name: string
  description: string
  monogram: string
  color: string
  kind: 'investment' | 'bank'
  holdingsDate: string
  priceDate?: string
}

export const accounts: readonly Account[] = [
  { id: 'ind-in', name: 'INDmoney', description: 'Indian stocks & direct funds', monogram: 'in', color: 'green', kind: 'investment', holdingsDate: '20 Oct 2026, 17:30 IST', priceDate: AS_OF },
  { id: 'ind-us', name: 'INDmoney US', description: 'US stocks & ETFs', monogram: 'in', color: 'blue', kind: 'investment', holdingsDate: '20 Oct 2026, 09:00 IST', priceDate: '20 Oct 2026, 01:30 IST' },
  { id: 'advisor', name: 'Advisor funds', description: 'Regular mutual funds', monogram: 'mf', color: 'purple', kind: 'investment', holdingsDate: '18 Oct 2026, 10:00 IST', priceDate: AS_OF },
  { id: 'ubs', name: 'UBS', description: 'Accenture employee shares', monogram: 'ub', color: 'stone', kind: 'investment', holdingsDate: '20 Oct 2026, 09:00 IST', priceDate: '20 Oct 2026, 01:30 IST' },
  { id: 'hdfc', name: 'HDFC Bank', description: 'Savings account', monogram: 'H', color: 'blue', kind: 'bank', holdingsDate: '20 Oct 2026, 10:00 IST' },
  { id: 'sbi', name: 'SBI', description: 'Savings account', monogram: 'S', color: 'sky', kind: 'bank', holdingsDate: '20 Oct 2026, 10:00 IST' },
]

export interface Position { id: string; accountId: string; category: AssetClass; value: Money | null; label: string }
const cashPositions: readonly Position[] = [
  { id: 'broker-in', accountId: 'ind-in', category: 'cash', label: 'Broker cash · INR', value: money('18500') },
  { id: 'broker-us', accountId: 'ind-us', category: 'cash', label: 'Broker cash · USD', value: money('120', 'USD') },
  { id: 'hdfc-cash', accountId: 'hdfc', category: 'cash', label: 'Bank cash · HDFC', value: money('186420') },
  { id: 'sbi-cash', accountId: 'sbi', category: 'cash', label: 'Bank cash · SBI', value: money('74850') },
]

export function getPositions(partial = false): Position[] {
  const investments: Position[] = getHoldings(partial).map(holding => ({
    id: holding.id, accountId: holding.accountId, value: holding.value,
    category: holding.instrument.type === 'fund' ? 'funds' : holding.instrument.market === 'US' ? 'us' : 'india',
    label: `${holding.instrument.name}${holding.instrument.plan ? ` · ${holding.instrument.plan} · ${holding.instrument.option}` : ''}`,
  }))
  return [...investments, ...cashPositions.map(position => ({ ...position }))]
}

export const assetClasses: readonly { id: AssetClass; label: string; note: string }[] = [
  { id: 'us', label: 'US equities', note: 'Stocks, ETFs & employee shares' },
  { id: 'funds', label: 'Mutual funds', note: 'Direct & regular plans' },
  { id: 'india', label: 'Indian equities', note: 'Stocks & ETFs' },
  { id: 'cash', label: 'Cash', note: 'Bank & broker balances' },
]

export function getSummary(items: readonly Position[]) {
  const known = items.filter((item): item is Position & { value: Money } => item.value !== null)
  const invested = sum(known.filter(item => item.category !== 'cash').map(item => item.value))
  const cash = sum(known.filter(item => item.category === 'cash').map(item => item.value))
  return { invested, cash, total: sum([invested, cash]), missing: items.length - known.length }
}

export function getAccountValue(items: readonly Position[], id: string): Money | null {
  const selected = items.filter(item => item.accountId === id)
  return selected.some(item => item.value === null) ? null : sum(selected.flatMap(item => item.value ? [item.value] : []))
}

export const history = [
  ['2026-04-21', '4160000'], ['2026-04-28', '4250000'], ['2026-05-05', '4220000'],
  ['2026-05-12', '4320000'], ['2026-05-19', '4290000'], ['2026-05-26', '4380000'],
  ['2026-06-02', '4410000'], ['2026-06-09', '4350000'], ['2026-06-16', '4470000'],
  ['2026-06-23', '4500000'], ['2026-06-30', '4460000'], ['2026-07-07', '4540000'],
  ['2026-07-14', '4630000'], ['2026-07-21', '4590000'], ['2026-07-28', '4650000'],
  ['2026-08-04', '4600000'], ['2026-08-11', '4740000'], ['2026-08-18', '4800000'],
  ['2026-08-25', '4750000'], ['2026-09-01', '4810000'], ['2026-09-08', '4880000'],
  ['2026-09-15', '4810000'], ['2026-09-22', '4930000'], ['2026-09-29', '4970000'],
  ['2026-10-06', '4920000'], ['2026-10-13', '5020000'], ['2026-10-20', '5086080'],
].map(([date = '', value = '0']) => ({ date, value: money(value) }))

export function shortDate(date: string): string {
  return new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', timeZone: 'UTC' }).format(new Date(`${date}T12:00:00Z`))
}

export interface Activity { id: string; title: string; detail: string; date: string; kind: 'purchase' | 'dividend' | 'transfer' | 'spending'; value: Money }
export const activity: readonly Activity[] = [
  { id: 'a1', title: 'Monthly fund investment', detail: 'INDmoney · Direct plan', date: '2026-10-20', kind: 'purchase', value: money('15000') },
  { id: 'a2', title: 'Dividend received', detail: 'UBS · Accenture shares', date: '2026-10-19', kind: 'dividend', value: money('42.50', 'USD') },
  { id: 'a3', title: 'Transfer between accounts', detail: 'HDFC Bank → SBI · Matched pair', date: '2026-10-18', kind: 'transfer', value: money('25000') },
  { id: 'a4', title: 'Everyday groceries', detail: 'HDFC Bank · Food & groceries', date: '2026-10-18', kind: 'spending', value: money('2450') },
]

export function spendingTotal(items: readonly Activity[]): Money {
  return sum(items.filter(item => item.kind === 'spending').map(item => item.value))
}
