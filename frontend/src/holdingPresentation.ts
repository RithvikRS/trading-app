import { accounts } from './data/portfolio'

export const typeLabels = { stock: 'Stock', etf: 'ETF', fund: 'Mutual fund' }
export function accountName(id: string) { return id === 'ind-in' ? 'INDmoney India' : accounts.find(account => account.id === id)?.name ?? 'Unknown account' }
export function sourceDate(date: string) {
  return new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', timeZone: 'Asia/Kolkata' }).format(new Date(date))
}
export function sourceTimestamp(date: string) {
  return new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Kolkata', hourCycle: 'h23' }).format(new Date(date)) + ' IST'
}
export function recordDate(date: string) {
  return new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' }).format(new Date(`${date}T00:00:00Z`))
}
