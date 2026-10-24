export type Account = {
  id: string
  kind: 'bank' | 'brokerage' | 'mutual_fund' | 'employee_stock'
  institution: 'hdfc' | 'sbi' | 'indmoney' | 'fund_registrar' | 'ubs'
  market: 'IN' | 'US'
  label: string
  currencies: ('INR' | 'USD')[]
  revision: number
  state: 'active' | 'archived'
}
export type AccountPage = { items: Account[]; next_after: string | null }
export type AccountCursor = { after: string | null; previous: (string | null)[] }
export type AccountsState =
  | { kind: 'idle' }
  | { kind: 'loading'; cursor: AccountCursor }
  | { kind: 'ready'; cursor: AccountCursor; page: AccountPage }
  | { kind: 'failed'; cursor: AccountCursor; limited: boolean }
export type AccountNavigation = 'first' | 'refresh' | 'next' | 'previous'
export const ACCOUNT_PAGE_SIZE = 25
export const MAX_ACCOUNT_PAGES = 100
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/
const identifier = (value: unknown): value is string => typeof value === 'string' && uuid.test(value) && value !== '00000000-0000-0000-0000-000000000000'
const object = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value)
const exact = (value: Record<string, unknown>, keys: string[]) => Object.keys(value).length === keys.length && Object.keys(value).every(key => keys.includes(key))
const member = (value: unknown, choices: string[]) => typeof value === 'string' && choices.includes(value)
const invalid = () => new Error('Account response is unavailable.')

export function parseAccountPage(value: unknown, after: string | null): AccountPage {
  if ((after !== null && !identifier(after)) || !object(value) || !exact(value, ['items', 'next_after']) || !Array.isArray(value.items) || value.items.length > ACCOUNT_PAGE_SIZE || (value.next_after !== null && !identifier(value.next_after))) throw invalid()
  let previous = after
  for (const item of value.items) {
    if (!object(item) || !exact(item, ['id', 'kind', 'institution', 'market', 'label', 'currencies', 'revision', 'state']) || !identifier(item.id) || (previous !== null && item.id <= previous) || !member(item.kind, ['bank', 'brokerage', 'mutual_fund', 'employee_stock']) || !member(item.institution, ['hdfc', 'sbi', 'indmoney', 'fund_registrar', 'ubs']) || !member(item.market, ['IN', 'US']) || typeof item.label !== 'string' || item.label.length < 1 || [...item.label].length > 64 || /[\u0000-\u001f\u007f]/.test(item.label) || !Array.isArray(item.currencies) || item.currencies.length < 1 || item.currencies.length > 2 || item.currencies.some(currency => !member(currency, ['INR', 'USD'])) || new Set(item.currencies).size !== item.currencies.length || !Number.isSafeInteger(item.revision) || Number(item.revision) < 1 || !member(item.state, ['active', 'archived'])) throw invalid()
    previous = item.id
  }
  if (value.next_after !== null && (value.items.length !== ACCOUNT_PAGE_SIZE || value.next_after !== previous)) throw invalid()
  return value as AccountPage
}

export function accountCursor(state: AccountsState, direction: AccountNavigation): AccountCursor | undefined {
  if (state.kind === 'loading') return undefined
  if (direction === 'first') return { after: null, previous: [] }
  if (state.kind === 'idle') return undefined
  if (direction === 'refresh') return state.cursor
  if (direction === 'previous' && state.cursor.previous.length) return { after: state.cursor.previous.at(-1)!, previous: state.cursor.previous.slice(0, -1) }
  if (direction === 'next' && state.kind === 'ready' && state.page.next_after && state.cursor.previous.length < MAX_ACCOUNT_PAGES - 1) return { after: state.page.next_after, previous: [...state.cursor.previous, state.cursor.after] }
  return undefined
}
