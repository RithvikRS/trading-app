import { createContext, useContext } from 'react'
import type { ReactNode } from 'react'
import { formatMoney } from './data/money'
import type { Money } from './data/money'
import type { Preferences } from './preferences'

export const DisplayContext = createContext<Preferences>({ theme: 'light', currency: 'INR', hidden: false })

export function PrivateValue({ children }: { children: ReactNode }) {
  const { hidden } = useContext(DisplayContext)
  return hidden ? <span className="masked-amount" aria-label="Amount hidden"><span aria-hidden="true">••••••</span></span> : <>{children}</>
}

export function Amount({ value, original = false }: { value: Money | null; original?: boolean }) {
  const { currency, hidden } = useContext(DisplayContext)
  if (hidden) return <PrivateValue>{null}</PrivateValue>
  if (value === null) return <span className="unavailable" aria-label="Value unavailable">—</span>
  return <span className="amount">{formatMoney(value, original ? value.currency : currency)}</span>
}
