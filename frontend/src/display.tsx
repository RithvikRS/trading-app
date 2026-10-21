import { createContext, useContext } from 'react'
import type { ReactNode } from 'react'
import { convertScaled, formatFixed, formatMoney } from './data/money'
import type { Currency, Money } from './data/money'
import { QUOTE_SCALE } from './data/holdings'
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

export function ReportingAmount({ value }: { value: Money | null }) {
  const { currency, hidden } = useContext(DisplayContext)
  return <span className="reporting-amount"><Amount value={value} />{!hidden && value && value.currency !== currency && <small className="original-value">Original {value.currency} · <Amount value={value} original /></small>}</span>
}

export function QuoteValue({ value, currency: sourceCurrency }: { value: bigint; currency: Currency }) {
  const { currency, hidden } = useContext(DisplayContext)
  if (hidden) return <PrivateValue>{null}</PrivateValue>
  return <span className="reporting-amount"><span className="holding-number detail-quote">{currency === 'INR' ? '₹' : '$'}{formatFixed(convertScaled(value, sourceCurrency, currency), QUOTE_SCALE, 2)}</span>{sourceCurrency !== currency && <small className="original-value">Original {sourceCurrency} · <span>{sourceCurrency === 'INR' ? '₹' : '$'}{formatFixed(value, QUOTE_SCALE, 2)}</span></small>}</span>
}
