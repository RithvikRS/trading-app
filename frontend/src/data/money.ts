export type Currency = 'INR' | 'USD'
export type Money = Readonly<{ minor: bigint; currency: Currency }>

// Fictional fixture rate: 1 USD = 83.50 INR.
const INR_PER_USD_NUMERATOR = 8350n
const INR_PER_USD_DENOMINATOR = 100n

export function money(decimal: string, currency: Currency = 'INR'): Money {
  return { minor: parseFixed(decimal, 2), currency }
}

export function parseFixed(decimal: string, scale: number): bigint {
  if (!Number.isInteger(scale) || scale < 0 || scale > 8) throw new Error('Unsupported decimal scale')
  if (!/^-?\d+(\.\d+)?$/.test(decimal)) throw new Error('Expected an exact decimal string')
  const negative = decimal.startsWith('-')
  const [whole = '0', fraction = ''] = decimal.replace('-', '').split('.')
  if (fraction.length > scale) throw new Error('Amount exceeds its declared precision')
  return (BigInt(whole) * 10n ** BigInt(scale) + BigInt(fraction.padEnd(scale, '0') || '0')) * (negative ? -1n : 1n)
}

export function divideRounded(numerator: bigint, denominator: bigint): bigint {
  if (denominator <= 0n) throw new Error('Expected a positive denominator')
  const absolute = numerator < 0n ? -numerator : numerator
  return ((absolute + denominator / 2n) / denominator) * (numerator < 0n ? -1n : 1n)
}

export function convert(value: Money, currency: Currency): Money {
  if (value.currency === currency) return value
  const minor = currency === 'INR'
    ? divideRounded(value.minor * INR_PER_USD_NUMERATOR, INR_PER_USD_DENOMINATOR)
    : divideRounded(value.minor * INR_PER_USD_DENOMINATOR, INR_PER_USD_NUMERATOR)
  return { minor, currency }
}

export function sum(values: readonly Money[], currency: Currency = 'INR'): Money {
  return { currency, minor: values.reduce((total, value) => total + convert(value, currency).minor, 0n) }
}

// Number conversion is for presentation only, after exact arithmetic. Fixtures are safely bounded.
export function formatMoney(value: Money, currency = value.currency): string {
  const { minor } = convert(value, currency)
  if (minor > BigInt(Number.MAX_SAFE_INTEGER) || minor < -BigInt(Number.MAX_SAFE_INTEGER)) throw new Error('Amount exceeds supported display precision')
  return new Intl.NumberFormat(currency === 'INR' ? 'en-IN' : 'en-US', {
    style: 'currency', currency, minimumFractionDigits: currency === 'USD' ? 2 : 0, maximumFractionDigits: 2,
  }).format(Number(minor) / 100)
}

export function formatFixed(value: bigint, scale: number, minimumFractionDigits = 0): string {
  const absolute = value < 0n ? -value : value
  const factor = 10n ** BigInt(scale)
  const whole = new Intl.NumberFormat('en-US').format(absolute / factor)
  const fraction = (absolute % factor).toString().padStart(scale, '0').replace(/0+$/, '').padEnd(minimumFractionDigits, '0')
  return `${value < 0n ? '-' : ''}${whole}${fraction ? `.${fraction}` : ''}`
}

export function axisLabel(value: Money, currency: Currency): string {
  const units = Number(convert(value, currency).minor) / 100
  return currency === 'INR' ? `₹${(units / 100_000).toFixed(1)}L` : `$${(units / 1000).toFixed(1)}k`
}
