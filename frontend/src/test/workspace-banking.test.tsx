import { StrictMode } from 'react'
import { act, fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import axe from 'axe-core'
import Workspace from '../../workspace/src/Workspace'
import { AuthController } from '../../workspace/src/auth'
import { bankAccount, bankAccountPage, bankActivityPage, bankHistory } from '../../workspace/src/banking-evidence'
import { accountActivityPage, activityPage, eventEvidence, eventIdentity } from '../../workspace/src/activity-evidence'
import type { Account } from '../../workspace/src/accounts'

const id = (n: number) => `76000000-0000-4000-8000-${String(n).padStart(12, '0')}`
const hdfc: Account = { id: id(1), kind: 'bank', institution: 'hdfc', market: 'IN', label: 'Everyday account', currencies: ['INR', 'USD'], revision: 1, state: 'active' }
const sbi: Account = { ...hdfc, id: id(2), institution: 'sbi', label: 'Savings account', currencies: ['INR'], state: 'archived' }
const brokerage: Account = { ...hdfc, id: id(3), kind: 'brokerage', institution: 'indmoney', label: 'Investments' }
const cash = (source = '-1500.00', currency = 'INR') => ({ role: 'net_cash', source, currency, missing_reason: null })
const event = (n = 30, account = id(1)) => ({ id: id(n), account_id: account, position_id: null, instrument_id: null, kind: 'cash_movement', revision: 2, is_current: true, account_state: 'active', status: 'active', posting_state: 'posted', correction_reason: 'source_correction', trade_date: null, settlement_date: null, booking_date: '2026-05-04', value_date: '2026-05-05', source_row_id: id(10), source_review_revision: 1, source_id: id(11), observation_id: id(12), batch_id: id(13), coverage: 'partial_activity', period_start: '2026-05-01', period_end: '2026-05-31', cash_date_basis: 'value', components: [cash(), { role: 'fee', source: null, currency: 'INR', missing_reason: 'not_supplied' }, { role: 'withholding', source: '0.00000000', currency: 'INR', missing_reason: null }] })
const fee = () => ({ ...event(31), kind: 'fee', components: [cash('-3.25')] })
const pending = () => ({ ...event(32), posting_state: 'pending', value_date: null, components: [cash('0.00', 'USD')] })
const cancelled = () => ({ ...event(33), status: 'cancelled', correction_reason: 'cancellation', components: [] })
const newer = () => ({ ...event(), revision: 3, source_row_id: id(110), source_review_revision: 4, source_id: id(111), observation_id: id(112), batch_id: id(113), coverage: 'snapshot', period_start: '2026-09-01', period_end: '2026-09-30', booking_date: '2026-09-04', value_date: null, cash_date_basis: 'booking', components: [cash('2150.50', 'USD')] })
const latest = () => [event(), fee(), pending(), cancelled()]
const root = () => eventIdentity(eventEvidence(event(), hdfc.id))
const history = () => [newer(), { ...event(), is_current: false }, { ...event(), revision: 1, correction_reason: null, is_current: false }]
const session = () => ({ status: 'authenticated', workspace_context: 'f'.repeat(64), expires_at: new Date(Date.now() + 28_800_000).toISOString(), idle_expires_at: new Date(Date.now() + 900_000).toISOString(), fresh_until: new Date(Date.now() + 300_000).toISOString(), factors: [id(99)], unverified_factors: [] })
const response = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store', Date: new Date().toUTCString() } })
const fetchMock = vi.fn<typeof fetch>()
let auth: AuthController, masked: boolean, currency: string, theme: string, preferenceRevision: number
beforeEach(() => {
  masked = false; currency = 'INR'; theme = 'light'; preferenceRevision = 1
  document.cookie = 'trading_dev_csrf=synthetic-csrf-value-long-enough; Path=/'
  vi.stubGlobal('fetch', fetchMock); fetchMock.mockReset(); auth = new AuthController()
  fetchMock.mockImplementation(async (path, options) => {
    if (path === '/api/v1/auth/bootstrap') return response({ status: 'ready', recovery_email_enabled: false })
    if (path === '/api/v1/auth/session') return response(session())
    if (path === '/api/v1/auth/logout') return response({ status: 'signed_out', provider_cleanup: 'complete' })
    if (path === '/api/v1/preferences') {
      if (options?.method === 'PUT') { const body = JSON.parse(String(options.body)); masked = body.amount_masked; currency = body.display_currency; theme = body.theme; preferenceRevision++ }
      return response({ amount_masked: masked, display_currency: currency, theme, revision: preferenceRevision })
    }
    if (path === '/api/v1/finance/accounts/query') return response({ items: [hdfc, sbi, brokerage], next_after: null })
    if (path === '/api/v1/finance/events/query') return response({ items: JSON.parse(String(options!.body)).account_id === sbi.id ? [{ ...event(40, sbi.id), account_state: 'archived', components: [cash('500.00')] }] : latest(), next_after: null })
    if (path === '/api/v1/finance/events/history') return response({ items: history(), next_before: null })
    return response({}, 404)
  })
})
afterEach(() => { auth.lock(); vi.unstubAllGlobals(); document.cookie = 'trading_dev_csrf=; Max-Age=0; Path=/'; delete document.documentElement.dataset.theme })
function override(path: string, handler: (body: Record<string, unknown>) => unknown, status = 200) { const previous = fetchMock.getMockImplementation()!; fetchMock.mockImplementation((url, options) => url === path ? Promise.resolve(response(handler(JSON.parse(String(options!.body))), status)) : previous(url, options)) }
async function openBanking(strict = false) {
  const workspace = <Workspace controller={auth} />; render(strict ? <StrictMode>{workspace}</StrictMode> : workspace); await screen.findByRole('heading', { name: 'A fresh start.' })
  fireEvent.click(within(screen.getByRole('navigation', { name: 'Workspace navigation' })).getByRole('button', { name: 'Banking' })); await screen.findByRole('heading', { name: 'Saved bank accounts on this page' })
}
async function openActivity() { await openBanking(); fireEvent.click(screen.getByRole('button', { name: 'View saved activity for HDFC Everyday account' })); await screen.findByRole('heading', { name: 'Saved account activity' }) }
const financeCalls = () => fetchMock.mock.calls.filter(([path]) => String(path).includes('/finance/'))

it('preserves validated HDFC/SBI accounts and the complete mixed directory cursor', () => {
  const items = Array.from({ length: 25 }, (_, n) => ({ ...brokerage, id: id(100 + n) })), value = { items, next_after: id(124) }
  expect(bankAccountPage(value)).toEqual(value); expect(bankAccount(sbi).state).toBe('archived')
  expect(bankAccount({ ...hdfc, currencies: ['USD'] }).currencies).toEqual(['USD'])
})
it.each([{ kind: 'bank', institution: 'ubs' }, { kind: 'bank', market: 'US' }, { kind: 'bank', institution: 'indmoney' }, { currencies: ['INR', 'INR'] }, { id: 'bad' }, { revision: 0 }, { label: 'bad\u0000label' }])('rejects invalid bank directory evidence %#', change => expect(() => bankAccountPage({ items: [{ ...hdfc, ...change }], next_after: null })).toThrow())
it('cannot choose a non-bank or forge a directory context', () => {
  expect(() => bankAccount(brokerage)).toThrow(); expect(() => bankAccount({ ...hdfc, currencies: ['EUR'] } as unknown as Account)).toThrow()
  for (const value of [{ items: [hdfc, hdfc], next_after: null }, { items: [sbi, hdfc], next_after: null }, { items: [hdfc], next_after: hdfc.id }, { items: [hdfc], next_after: null, extra: true }]) expect(() => bankAccountPage(value)).toThrow()
})
it('retains cash movements, fees, withholding, signed zeros and declared USD without income classification', () => {
  const items = [event(), fee(), pending(), cancelled(), { ...event(34), kind: 'withholding', components: [cash('-0.00')] }]
  expect(bankActivityPage({ items, next_after: null }, bankAccount(hdfc)).items).toEqual(items)
})
it.each([{ position_id: id(4), instrument_id: id(5) }, { position_id: id(4) }, { instrument_id: id(5) }, { account_id: id(999) }, { is_current: false }, { components: [cash('1.00', 'USD')] }])('rejects impossible bank latest binding %#', change => expect(() => bankActivityPage({ items: [{ ...event(30, sbi.id), ...change }], next_after: null }, bankAccount(sbi))).toThrow())
it.each(['buy', 'sell', 'subscription', 'redemption', 'dividend'])('rejects unsupported bank position economics: %s', kind => {
  const item = { ...event(), kind, position_id: id(4), instrument_id: id(5), trade_date: '2026-05-01', components: [cash(kind === 'sell' || kind === 'redemption' ? '1500.00' : kind === 'dividend' ? '5.00' : '-1500.00'), ...(kind === 'dividend' ? [] : [{ role: 'quantity', source: kind === 'sell' || kind === 'redemption' ? '-2' : '2', currency: null, missing_reason: null }])] }
  expect(() => bankActivityPage({ items: [item], next_after: null }, bankAccount(hdfc))).toThrow()
})
it.each([{ components: [cash(3.5 as unknown as string)] }, { components: [cash('1e3')] }, { components: [cash('-1.001')] }, { components: [cash(), cash()] }, { components: [cash(), { role: 'fee', source: null, currency: 'USD', missing_reason: 'not_supplied' }] }, { booking_date: '2026-02-30' }, { correction_reason: null }])('retains exact event validation before banking projection %#', change => expect(() => bankActivityPage({ items: [{ ...event(30, sbi.id), ...change }], next_after: null }, bankAccount(sbi))).toThrow())
it('retains bank paging order and rejects cross-account continuations', () => {
  const items = Array.from({ length: 25 }, (_, n) => event(100 + n)); expect(bankActivityPage({ items, next_after: id(124) }, bankAccount(hdfc)).next_after).toBe(id(124))
  expect(bankActivityPage({ items: [event(125)], next_after: null }, bankAccount(hdfc), id(124)).items).toHaveLength(1)
  for (const value of [{ items: [event(124)], next_after: null }, { items: [event(125, sbi.id)], next_after: null }, { items: [event(125)], next_after: id(125) }]) expect(() => bankActivityPage(value, bankAccount(hdfc), id(124))).toThrow()
})
it('preserves investment origin instrument validation while exposing account-only validation', () => {
  const position = { id: id(4), account_id: hdfc.id, instrument_id: id(5), holding_form: 'custody', account_state: 'active' }, item = { ...event(), position_id: id(4), instrument_id: id(6) }, value = { items: [item], next_after: null }
  expect(accountActivityPage(value, hdfc.id).items).toHaveLength(1); expect(() => activityPage(value, position)).toThrow()
  expect(activityPage({ items: [{ ...item, position_id: id(7) }], next_after: null }, position).items).toHaveLength(1)
})
it('allows changed source and values, equal/newer current history and older continuation revisions', () => {
  expect(bankHistory({ items: history(), next_before: null }, bankAccount(hdfc), root()).items).toEqual(history())
  expect(bankHistory({ items: [event()], next_before: null }, bankAccount(hdfc), root()).items).toHaveLength(1)
  expect(bankHistory({ items: [history()[2]], next_before: null }, bankAccount(hdfc), root(), 2).items[0]!.revision).toBe(1)
  const items = Array.from({ length: 25 }, (_, n) => ({ ...event(), revision: 30 - n, is_current: n === 0 }))
  expect(bankHistory({ items, next_before: 6 }, bankAccount(hdfc), root()).next_before).toBe(6)
})
it.each([{ id: id(999) }, { account_id: sbi.id }, { position_id: id(4), instrument_id: id(5) }, { kind: 'fee' }, { is_current: false }, { revision: 1, correction_reason: null }, { revision: 0 }, { revision: '2' }, { revision: 9007199254740992 }])('rejects changed event identity, bank linkage or regressed current history %#', change => expect(() => bankHistory({ items: [{ ...event(), ...change }], next_before: null }, bankAccount(hdfc), root())).toThrow())
it('rejects empty known-current history, malformed cursors and foreign currency in older revisions', () => {
  expect(() => bankHistory({ items: [], next_before: null }, bankAccount(hdfc), root())).toThrow()
  expect(() => bankHistory({ items: [event()], next_before: 2 }, bankAccount(hdfc), root())).toThrow()
  expect(() => bankHistory({ items: [{ ...event(30, sbi.id), components: [cash('2.00', 'USD')], is_current: false }], next_before: null }, bankAccount(sbi), { ...root(), account_id: sbi.id }, 3)).toThrow()
})
it('loads only one account page on Banking entry and explicitly opens bank activity without position reads', async () => {
  await openBanking(); expect(financeCalls().map(([path]) => path)).toEqual(['/api/v1/finance/accounts/query'])
  expect(screen.getByText(/INR native · Archived/)).toBeTruthy(); expect(screen.queryByRole('button', { name: /View saved activity for.*Investments/ })).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'View saved activity for HDFC Everyday account' })); const heading = await screen.findByRole('heading', { name: 'Saved account activity' }); expect(document.activeElement).toBe(heading)
  expect(screen.getByText('INR -1,500.00')).toBeTruthy(); expect(screen.getByText('USD 0.00')).toBeTruthy(); expect(screen.getByText('INR 0.00000000')).toBeTruthy()
  const call = financeCalls().at(-1)!; expect(JSON.parse(String(call[1]!.body))).toEqual({ account_id: hdfc.id, limit: 25, after: null }); expect(call[1]).toMatchObject({ method: 'POST', credentials: 'same-origin', cache: 'no-store', redirect: 'error' })
  expect(document.querySelectorAll('.wb-event')).toHaveLength(4); expect(document.querySelectorAll('.wb-event details[open]')).toHaveLength(0)
})
it('does not duplicate the initial bank read during StrictMode effect replay', async () => {
  await openBanking(true); expect(financeCalls().map(([path]) => path)).toEqual(['/api/v1/finance/accounts/query'])
})
it('defers the initial bank read while a session operation is busy', async () => {
  render(<Workspace controller={auth} />); await screen.findByRole('heading', { name: 'A fresh start.' }); let finish!: (response: Response) => void; const previous = fetchMock.getMockImplementation()!
  fetchMock.mockImplementation((path, options) => path === '/api/v1/auth/session' ? new Promise(resolve => { finish = resolve }) : previous(path, options))
  let checking!: Promise<void>; act(() => { checking = auth.check() }); fireEvent.click(within(screen.getByRole('navigation', { name: 'Workspace navigation' })).getByRole('button', { name: 'Banking' })); expect(financeCalls()).toHaveLength(0)
  await act(async () => { finish(response(session())); await checking }); await screen.findByRole('heading', { name: 'Saved bank accounts on this page' }); expect(financeCalls()).toHaveLength(1)
})
it('keeps mixed-directory pages navigable even when none of their accounts are banks', async () => {
  const first = Array.from({ length: 25 }, (_, n) => ({ ...brokerage, id: id(100 + n) })); override('/api/v1/finance/accounts/query', body => body.after ? { items: [{ ...sbi, id: id(125) }], next_after: null } : { items: first, next_after: id(124) })
  await openBanking(); expect(screen.getByText(/No HDFC or SBI bank accounts on this page/)).toBeTruthy(); fireEvent.click(screen.getByRole('button', { name: 'Next account page' })); await screen.findByRole('button', { name: 'View saved activity for SBI Savings account' })
  fireEvent.click(screen.getByRole('button', { name: 'Previous account page' })); await screen.findByText(/No HDFC or SBI bank accounts on this page/)
  expect(financeCalls().map(([, options]) => JSON.parse(String(options!.body)).after)).toEqual([null, id(124), null]); expect(financeCalls().every(([path]) => String(path).endsWith('/accounts/query'))).toBe(true)
})
it('clears values while changing accounts and permits archived-bank inspection', async () => {
  await openActivity(); fireEvent.click(screen.getByRole('button', { name: 'Choose another bank account' })); await screen.findByRole('button', { name: 'View saved activity for SBI Savings account' }); expect(screen.queryByText('INR -1,500.00')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'View saved activity for SBI Savings account' })); await screen.findByText('INR 500.00'); expect(screen.getByText(/Archived account/)).toBeTruthy(); expect(screen.queryByText('INR -1,500.00')).toBeNull()
})
it('refreshes activity with the current cursor and resets it on return from revision history', async () => {
  override('/api/v1/finance/events/query', body => body.after ? { items: [event(125)], next_after: null } : { items: Array.from({ length: 25 }, (_, n) => event(100 + n)), next_after: id(124) })
  override('/api/v1/finance/events/history', () => ({ items: [event(125)], next_before: null }))
  await openActivity(); fireEvent.click(screen.getByRole('button', { name: 'Next activity page' })); await screen.findByRole('button', { name: `Revision history for event ${id(125)}` }); fireEvent.click(screen.getByRole('button', { name: 'Refresh activity' })); await screen.findByRole('heading', { name: 'Saved account activity' })
  fireEvent.click(screen.getByRole('button', { name: `Revision history for event ${id(125)}` })); await screen.findByRole('heading', { name: 'Event revision history' }); fireEvent.click(screen.getByRole('button', { name: 'Back to saved activity' })); await screen.findByRole('button', { name: `Revision history for event ${id(100)}` })
  expect(financeCalls().filter(([path]) => String(path).endsWith('/events/query')).map(([, options]) => JSON.parse(String(options!.body)).after)).toEqual([null, id(124), id(124), null])
})
it('navigates newest and earlier event history without keeping previous amounts', async () => {
  override('/api/v1/finance/events/history', body => body.before ? { items: [{ ...event(), revision: 5, is_current: false, components: [cash('5.00')] }], next_before: null } : { items: Array.from({ length: 25 }, (_, n) => ({ ...event(), revision: 30 - n, is_current: n === 0, components: [cash('30.00')] })), next_before: 6 })
  await openActivity(); fireEvent.click(screen.getByRole('button', { name: `Revision history for event ${id(30)}` })); await screen.findByRole('heading', { name: 'Event revision history' }); fireEvent.click(screen.getByRole('button', { name: 'Earlier revisions' })); await screen.findByText('INR 5.00'); expect(screen.queryByText('INR 30.00')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'Refresh revisions' })); await screen.findByText('INR 5.00'); fireEvent.click(screen.getByRole('button', { name: 'Latest revisions' })); await screen.findAllByText('INR 30.00')
  expect(financeCalls().filter(([path]) => String(path).endsWith('/events/history')).map(([, options]) => JSON.parse(String(options!.body)).before)).toEqual([null, 6, 6, null])
})
it.each(['light', 'dark'])('masks historical/zero/missing bank values in %s mode', async appearance => {
  masked = true; theme = appearance; const storage = vi.spyOn(Storage.prototype, 'setItem'); await openActivity(); const view = document.querySelector('.wb-workspace')!
  expect(view.innerHTML).not.toMatch(/1500|1,500|0\.00000000|0\.00|3\.25|Not supplied by this revision/); expect(screen.getAllByText('••••')).toHaveLength(7); expect(storage).not.toHaveBeenCalled()
  expect((await axe.run(view, { rules: { 'color-contrast': { enabled: false }, region: { enabled: false } } })).violations).toEqual([])
  fireEvent.click(screen.getByRole('button', { name: `Revision history for event ${id(30)}` })); await screen.findByRole('heading', { name: 'Event revision history' }); expect(document.querySelector('.wb-workspace')!.innerHTML).not.toMatch(/2150|2,150|1500|1,500/)
})
it('preserves native values under display preference changes without finance requests', async () => {
  await openActivity(); const count = financeCalls().length; fireEvent.change(screen.getByLabelText('Display currency'), { target: { value: 'USD' } }); fireEvent.click(screen.getByRole('button', { name: 'Save preferences' })); await screen.findByText(/Your USD display preference/)
  expect(screen.getByText('INR -1,500.00')).toBeTruthy(); expect(screen.getByText('USD 0.00')).toBeTruthy(); expect(financeCalls()).toHaveLength(count)
})
it.each(['bank tuple', 'account', 'currency', 'position', 'history position', 'history currency', 'history regression', 'empty history'])('blocks malformed %s responses and clears old/returned values', async failure => {
  if (failure === 'bank tuple') { override('/api/v1/finance/accounts/query', () => ({ items: [{ ...hdfc, institution: 'ubs' }], next_after: null })); render(<Workspace controller={auth} />); await screen.findByRole('heading', { name: 'A fresh start.' }); fireEvent.click(within(screen.getByRole('navigation', { name: 'Workspace navigation' })).getByRole('button', { name: 'Banking' })) }
  else {
    if (failure.includes('currency')) { override('/api/v1/finance/accounts/query', () => ({ items: [{ ...hdfc, currencies: ['INR'] }], next_after: null })); override('/api/v1/finance/events/query', () => ({ items: [event()], next_after: null })) }
    await openActivity()
    if (failure.includes('history')) { override('/api/v1/finance/events/history', () => ({ items: failure === 'empty history' ? [] : [{ ...event(), ...(failure === 'history position' ? { position_id: id(4), instrument_id: id(5) } : failure === 'history currency' ? { components: [cash('2222.00', 'USD')] } : { revision: 1, correction_reason: null }) }], next_before: null })); fireEvent.click(screen.getByRole('button', { name: `Revision history for event ${id(30)}` })) }
    else { override('/api/v1/finance/events/query', () => ({ items: [{ ...event(), components: [cash('2222.00')], ...(failure === 'account' ? { account_id: id(999) } : failure === 'currency' ? { components: [cash('2222.00', 'USD')] } : { position_id: id(4), instrument_id: id(5) }) }], next_after: null })); fireEvent.click(screen.getByRole('button', { name: 'Refresh activity' })) }
  }
  await screen.findByRole('heading', { name: 'Unable to verify this response.' }); expect(auth.snapshot().screen).toMatchObject({ kind: 'blocked', reason: 'protocol' }); expect(document.body.innerHTML).not.toMatch(/1,500|1500|2,222|2222/); expect(document.querySelector('.wb-workspace')).toBeNull()
})
it('shows unavailable initial accounts without retrying, then explicitly reloads fresh directory context', async () => {
  override('/api/v1/finance/accounts/query', () => ({ detail: 'private bank evidence' }), 409); render(<Workspace controller={auth} />); await screen.findByRole('heading', { name: 'A fresh start.' }); fireEvent.click(within(screen.getByRole('navigation', { name: 'Workspace navigation' })).getByRole('button', { name: 'Banking' })); await screen.findByRole('alert'); expect(financeCalls()).toHaveLength(1); expect(document.body.textContent).not.toContain('private bank evidence')
  override('/api/v1/finance/accounts/query', () => ({ items: [hdfc], next_after: null })); fireEvent.click(screen.getByRole('button', { name: 'Reload saved bank accounts' })); await screen.findByRole('button', { name: 'View saved activity for HDFC Everyday account' }); expect(financeCalls()).toHaveLength(2)
})
it('drops selected financial context on an activity failure and requires fresh directory selection', async () => {
  await openActivity(); override('/api/v1/finance/events/query', () => ({ detail: 'private' }), 409); fireEvent.click(screen.getByRole('button', { name: 'Refresh activity' })); await screen.findByRole('alert'); expect(document.querySelectorAll('.wb-event')).toHaveLength(0); expect(screen.queryByText('HDFC · Everyday account')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'Reload saved bank accounts' })); await screen.findByRole('button', { name: 'View saved activity for HDFC Everyday account' }); expect(financeCalls().at(-1)![0]).toBe('/api/v1/finance/accounts/query')
})
it.each(['navigate', 'logout', 'lock', 'session'])('discards a late bank response after %s', async action => {
  await openActivity(); let finish!: (value: Response) => void; const previous = fetchMock.getMockImplementation()!
  fetchMock.mockImplementation((path, options) => path === '/api/v1/finance/events/history' ? new Promise(resolve => { finish = resolve }) : previous(path, options)); fireEvent.click(screen.getByRole('button', { name: `Revision history for event ${id(30)}` })); await screen.findByText('Checking saved bank evidence…'); expect(document.querySelectorAll('.wb-event')).toHaveLength(0)
  if (action === 'navigate') fireEvent.click(within(screen.getByRole('navigation', { name: 'Workspace navigation' })).getByRole('button', { name: 'Overview' }))
  else if (action === 'logout') fireEvent.click(screen.getByRole('button', { name: 'Sign out here' }))
  else if (action === 'session') { const pendingRequest = fetchMock.getMockImplementation()!; fetchMock.mockImplementation((path, options) => path === '/api/v1/auth/session' ? Promise.resolve(response({ ...session(), workspace_context: 'e'.repeat(64) })) : pendingRequest(path, options)); await act(async () => { auth.suspend(); await auth.bootstrap() }) }
  else await act(async () => auth.lock())
  await act(async () => finish(response({ items: history(), next_before: null }))); expect(document.querySelector('.wb-workspace')).toBeNull(); expect(document.body.innerHTML).not.toMatch(/1,500|2,150/)
})
it('clears a displayed bank view when an idle check observes a replaced session', async () => {
  await openActivity(); const previous = fetchMock.getMockImplementation()!; fetchMock.mockImplementation((path, options) => path === '/api/v1/auth/session' ? Promise.resolve(response({ ...session(), workspace_context: 'e'.repeat(64) })) : previous(path, options)); await act(async () => auth.check()); expect(auth.snapshot().screen).toMatchObject({ kind: 'blocked', reason: 'context' }); expect(document.querySelector('.wb-workspace')).toBeNull()
})
it('supports keyboard selection/history and a genuinely empty activity page', async () => {
  await openBanking(); const user = userEvent.setup(); screen.getByRole('button', { name: 'View saved activity for HDFC Everyday account' }).focus(); await user.keyboard('{Enter}'); const heading = await screen.findByRole('heading', { name: 'Saved account activity' }); expect(document.activeElement).toBe(heading)
  screen.getByRole('button', { name: `Revision history for event ${id(30)}` }).focus(); await user.keyboard('{Enter}'); expect(document.activeElement).toBe(await screen.findByRole('heading', { name: 'Event revision history' }))
  override('/api/v1/finance/events/query', () => ({ items: [], next_after: null })); fireEvent.click(screen.getByRole('button', { name: 'Back to saved activity' })); await screen.findByText(/No saved events on this page/); expect((screen.getByRole('button', { name: 'Next activity page' }) as HTMLButtonElement).disabled).toBe(true)
  expect(financeCalls().every(([path]) => ['/api/v1/finance/accounts/query', '/api/v1/finance/events/query', '/api/v1/finance/events/history'].includes(String(path)))).toBe(true)
})

it('requires a fresh directory selection before accepting a newly declared native currency', async () => {
  override('/api/v1/finance/accounts/query', () => ({ items: [{ ...hdfc, currencies: ['INR'] }], next_after: null }))
  override('/api/v1/finance/events/query', () => ({ items: [event()], next_after: null }))
  await openActivity(); override('/api/v1/finance/events/query', () => ({ items: [{ ...event(), components: [cash('2222.00', 'USD')] }], next_after: null }))
  fireEvent.click(screen.getByRole('button', { name: 'Refresh activity' })); await screen.findByRole('heading', { name: 'Unable to verify this response.' })
  expect(financeCalls().filter(([path]) => String(path).endsWith('/accounts/query'))).toHaveLength(1)
  override('/api/v1/finance/accounts/query', () => ({ items: [hdfc], next_after: null }))
  fireEvent.click(screen.getByRole('button', { name: 'Check again' })); await screen.findByRole('heading', { name: 'A fresh start.' })
  fireEvent.click(within(screen.getByRole('navigation', { name: 'Workspace navigation' })).getByRole('button', { name: 'Banking' })); await screen.findByRole('button', { name: 'View saved activity for HDFC Everyday account' })
  fireEvent.click(screen.getByRole('button', { name: 'View saved activity for HDFC Everyday account' })); await screen.findByText('USD 2,222.00')
  expect(financeCalls().filter(([path]) => String(path).endsWith('/accounts/query'))).toHaveLength(2)
})
it('discards a delayed initial directory response after leaving Banking', async () => {
  let finish!: (value: Response) => void; const previous = fetchMock.getMockImplementation()!
  fetchMock.mockImplementation((path, options) => path === '/api/v1/finance/accounts/query' ? new Promise(resolve => { finish = resolve }) : previous(path, options))
  render(<Workspace controller={auth} />); await screen.findByRole('heading', { name: 'A fresh start.' })
  fireEvent.click(within(screen.getByRole('navigation', { name: 'Workspace navigation' })).getByRole('button', { name: 'Banking' })); await act(async () => {}); expect(financeCalls()).toHaveLength(1)
  fireEvent.click(within(screen.getByRole('navigation', { name: 'Workspace navigation' })).getByRole('button', { name: 'Overview' }))
  await act(async () => finish(response({ items: [hdfc], next_after: null })))
  expect(document.querySelector('.wb-workspace')).toBeNull(); expect(screen.queryByText('Everyday account')).toBeNull()
})

it('keeps evidence states visible while ordering explanations are expandable', async () => {
  await openActivity(); const user = userEvent.setup(), summary = screen.getByText('About saved activity'), details = summary.closest('details')!
  expect(details.open).toBe(false); expect(screen.getByText('Pending evidence is not a posted movement.')).toBeTruthy(); expect(screen.getByText('Cancelled record. This revision has no amounts; earlier amounts remain in history.')).toBeTruthy()
  expect(screen.getByText('Unavailable · not supplied')).toBeTruthy(); expect(screen.getAllByText('Not supplied by this revision')).toHaveLength(2)
  await user.click(summary); expect(details.open).toBe(true); expect(within(details).getByText(/Identity order is not date order/)).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: `Revision history for event ${id(30)}` })); await screen.findByRole('heading', { name: 'Event revision history' }); expect(screen.getByText('About revision history').closest('details')!.open).toBe(false)
})
