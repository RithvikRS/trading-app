import { act, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import axe from 'axe-core'
import Workspace from '../../workspace/src/Workspace'
import { AuthController } from '../../workspace/src/auth'
import { lotObservation, lotPage, observationHistory, observationPage } from '../../workspace/src/lot-evidence'
import type { Lot } from '../../workspace/src/lot-evidence'

const id = (n: number) => `71000000-0000-4000-8000-${String(n).padStart(12, '0')}`
const position = { id: id(2), account_id: id(1), instrument_id: id(3), holding_form: 'custody', account_state: 'active' }
const lot: Lot = { id: id(4), position_id: id(2), account_id: id(1), instrument_id: id(3), account_state: 'active' }
const security = { id: id(3), name: 'Saved employee-share instrument', isin: 'ZZ0000000016', asset_class: 'equity', fund_scheme_id: null, fund_plan: null, fund_option: null, fund_currency: null }
const account = { id: id(1), kind: 'employee_stock', institution: 'ubs', market: 'US', label: 'Employee shares', currencies: ['INR', 'USD'], revision: 1, state: 'active' }
const quantity = (source = '12.123456789012') => ({ role: 'quantity', source, currency: null, missing_reason: null })
const components = [quantity(), { role: 'unit_price', source: '325.123456789012', currency: 'USD', missing_reason: null }, { role: 'acquisition_cost', source: '1500.00000000', currency: 'USD', missing_reason: null }, { role: 'discount_amount', source: '2500.00', currency: 'INR', missing_reason: null }, { role: 'reported_tax_basis', source: null, currency: 'USD', missing_reason: 'incomplete_history' }]
const observation = (n = 30) => ({
  ...lot, id: id(n), lot_id: lot.id, revision: 2, is_current: true, scope: 'lot_acquisition', correction_reason: 'source_correction', status: 'active', components,
  as_of_date: '2026-10-25', acquisition_date: '2026-05-01', booking_date: null,
  source_row_id: id(10), source_review_revision: 1, source_id: id(11), observation_id: id(12), batch_id: id(13),
  coverage: 'partial_activity', period_start: '2026-05-01', period_end: '2026-10-25', cash_date_basis: null,
})
const remaining = () => ({ ...observation(31), scope: 'lot_remaining', components: [quantity('0.000000000000')], acquisition_date: null })
const cancelled = () => ({ ...observation(32), status: 'cancelled', correction_reason: 'cancellation', components: [], as_of_date: null, acquisition_date: null, booking_date: '2026-10-25' })
const session = () => ({ status: 'authenticated', workspace_context: 'b'.repeat(64), expires_at: new Date(Date.now() + 28_800_000).toISOString(), idle_expires_at: new Date(Date.now() + 900_000).toISOString(), fresh_until: new Date(Date.now() + 300_000).toISOString(), factors: [id(99)], unverified_factors: [] })
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
    if (path === '/api/v1/preferences') {
      if (options?.method === 'PUT') { const body = JSON.parse(String(options.body)); masked = body.amount_masked; currency = body.display_currency; theme = body.theme; preferenceRevision++ }
      return response({ amount_masked: masked, display_currency: currency, theme, revision: preferenceRevision })
    }
    if (path === '/api/v1/finance/accounts/query') return response({ items: [account], next_after: null })
    if (path === '/api/v1/finance/investments/query') return response({ items: [{ ...position, instrument: security, choices: [] }], next_after: null })
    if (path === '/api/v1/finance/lots/query') return response({ items: [lot], next_after: null })
    if (path === '/api/v1/finance/lots/observations/query') return response({ items: [observation(), remaining(), cancelled()], next_after: null })
    if (path === '/api/v1/finance/lots/observations/history') return response({ items: [observation(), { ...observation(), revision: 1, is_current: false, correction_reason: null, components: [quantity('15.0000')] }], next_before: null })
    return response({}, 404)
  })
})
afterEach(() => { auth.lock(); vi.unstubAllGlobals(); document.cookie = 'trading_dev_csrf=; Max-Age=0; Path=/'; delete document.documentElement.dataset.theme })
async function openLots() {
  render(<Workspace controller={auth} />); await screen.findByRole('heading', { name: 'A fresh start.' })
  fireEvent.click(within(screen.getByRole('navigation', { name: 'Workspace navigation' })).getByRole('button', { name: 'Investments' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Choose an account' }))
  fireEvent.change(await screen.findByLabelText('Saved account'), { target: { value: account.id } })
  fireEvent.click(screen.getByRole('button', { name: 'View positions' }))
  fireEvent.click(await screen.findByRole('button', { name: /Saved employee-share instrument/ }))
  fireEvent.click(screen.getByRole('button', { name: 'Inspect lot evidence' }))
  await screen.findByRole('heading', { name: 'Lot evidence' })
}
async function openObservations() { await openLots(); fireEvent.click(screen.getByRole('button', { name: `Inspect observations for lot ${lot.id}` })); await screen.findByRole('button', { name: `Inspect revisions for observation ${id(30)}` }) }
function override(path: string, handler: (body: Record<string, unknown>) => unknown, status = 200) {
  const original = fetchMock.getMockImplementation()!
  fetchMock.mockImplementation((url, options) => url === path ? Promise.resolve(response(handler(JSON.parse(String(options!.body))), status)) : original(url, options))
}

it('preserves exact lot components, independent native currencies and zero remaining quantity', () => {
  expect(lotObservation(observation(), lot).components).toEqual(components)
  expect(lotObservation(remaining(), lot).components[0]!.source).toBe('0.000000000000')
  expect(lotObservation(cancelled(), lot).components).toEqual([])
  expect(lotPage({ items: [lot], next_after: null }, position).items[0]).toEqual(lot)
})
it.each([
  { lot_id: id(90) }, { position_id: id(90) }, { account_id: id(90) }, { instrument_id: id(90) },
  { revision: true }, { is_current: 'true' }, { scope: 'tax_lot' }, { status: 'pending' },
  { acquisition_date: '0000-01-01' }, { acquisition_date: '2026-02-30' }, { acquisition_date: '2026-10-26' }, { as_of_date: null },
  { period_end: null }, { period_end: '2026-04-30' }, { coverage: 'verified' },
  { revision: 1 }, { correction_reason: 'cancellation' }, { account_state: 'disabled' },
  { components: [quantity('0.00')] }, { components: [quantity('-1')] }, { components: [quantity(), quantity()] },
  { components: [{ ...quantity(), source: 1.2 }] }, { components: [{ ...quantity(), source: '1e2' }] },
  { components: [{ ...quantity(), source: '0.1234567890123' }] }, { components: [{ ...quantity(), currency: 'USD' }] },
  { components: [quantity(), { role: 'net_cash', source: '1.00', currency: 'USD', missing_reason: null }] },
  { components: [quantity(), { role: 'reported_tax_basis', source: '-1', currency: 'USD', missing_reason: null }] },
  { components: [quantity(), { role: 'fee', source: null, currency: 'USD', missing_reason: null }] },
  { private_reference: 'unexpected' },
])('rejects malformed or foreign lot observations %#', change => { expect(() => lotObservation({ ...observation(), ...change }, lot)).toThrow() })
it('rejects invalid current pages, scope changes, cancellation values and revision cursors', () => {
  expect(() => observationPage({ items: [{ ...observation(), is_current: false }], next_after: null }, lot)).toThrow()
  expect(() => lotObservation({ ...cancelled(), components: [quantity()] }, lot)).toThrow()
  expect(() => lotObservation({ ...cancelled(), booking_date: null }, lot)).toThrow()
  const root = lotObservation(observation(), lot)
  expect(() => observationHistory({ items: [remaining()], next_before: null }, lot, root)).toThrow()
  expect(() => observationHistory({ items: [root, root], next_before: null }, lot, root)).toThrow()
  expect(() => observationHistory({ items: [root], next_before: root.revision }, lot, root)).toThrow()
  expect(() => observationHistory({ items: [root], next_before: null }, lot, root, root.revision)).toThrow()
  expect(() => lotPage({ items: [{ ...lot, account_id: id(90) }], next_after: null }, position)).toThrow()
  expect(() => observationPage({ items: Array.from({ length: 26 }, (_, n) => observation(n + 100)), next_after: null }, lot)).toThrow()
})
it('rejects a first history page older than the observation revision used to open it', () => {
  const root = lotObservation(observation(), lot)
  const older = { ...observation(), revision: 1, correction_reason: null, components: [quantity('15.0000')] }
  expect(() => observationHistory({ items: [older], next_before: null }, lot, root)).toThrow()
})
it('accepts equal and newer first history revisions without binding changed source values', () => {
  const root = lotObservation(observation(), lot)
  expect(observationHistory({ items: [observation()], next_before: null }, lot, root).items[0]?.revision).toBe(2)
  const newer = { ...observation(), revision: 3, source_row_id: id(110), batch_id: id(113), as_of_date: '2026-10-26', components: [quantity('13.0000')] }
  const history = observationHistory({ items: [newer, { ...observation(), is_current: false }], next_before: null }, lot, root)
  expect(history.items.map(item => item.revision)).toEqual([3, 2])
  expect(history.items[0]?.components[0]?.source).toBe('13.0000')
})
it('accepts older historical revisions on a subsequent cursor page', () => {
  const root = lotObservation(observation(), lot)
  const older = { ...observation(), revision: 1, is_current: false, correction_reason: null, components: [quantity('15.0000')] }
  const history = observationHistory({ items: [older], next_before: null }, lot, root, 2)
  expect(history.items.map(item => item.revision)).toEqual([1]); expect(history.items[0]?.is_current).toBe(false)
})
it('blocks regressed first history responses and clears previous and returned financial values', async () => {
  await openObservations()
  expect(screen.getByText('12.123456789012')).toBeTruthy()
  override('/api/v1/finance/lots/observations/history', () => ({ items: [{ ...observation(), revision: 1, correction_reason: null, components: [quantity('15.0000')] }], next_before: null }))
  fireEvent.click(screen.getByRole('button', { name: `Inspect revisions for observation ${id(30)}` }))
  await screen.findByRole('heading', { name: 'Unable to verify this response.' })
  expect(auth.snapshot().screen).toMatchObject({ kind: 'blocked', reason: 'protocol' })
  expect(screen.queryByRole('heading', { name: 'Lot evidence' })).toBeNull()
  expect(document.body.innerHTML).not.toMatch(/12\.123456789012|15\.0000|1,500\.00000000/)
})
it.each(['INR', 'USD'])('shows only native exact evidence for %s preference without deriving balances or basis', async preference => {
  currency = preference; await openObservations()
  expect(screen.getByText('12.123456789012')).toBeTruthy()
  expect(screen.getByText('0.000000000000')).toBeTruthy()
  expect(screen.getByText('USD 1,500.00000000')).toBeTruthy()
  expect(screen.getByText('INR 2,500.00')).toBeTruthy()
  expect(screen.getByText('Unavailable · incomplete history')).toBeTruthy()
  expect(screen.getByText(new RegExp(`${preference} is your display preference`))).toBeTruthy()
  expect(screen.getByText(/They are not summed or automatically selected/)).toBeTruthy()
  expect(screen.getByText(/This revision withdraws the observation/)).toBeTruthy()
  expect(screen.getAllByText('Not supplied by this observation').length).toBeGreaterThan(0)
  expect(fetchMock.mock.calls.filter(([path]) => String(path).includes('/finance/')).every(([path]) => !String(path).includes('snapshot-review'))).toBe(true)
})
it('applies saved currency and privacy changes to the open lot view without converting evidence', async () => {
  await openObservations()
  const reads = fetchMock.mock.calls.filter(([path]) => String(path).startsWith('/api/v1/finance/')).length
  fireEvent.change(screen.getByLabelText('Display currency'), { target: { value: 'USD' } })
  fireEvent.change(screen.getByLabelText('Amount privacy'), { target: { value: 'hidden' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save preferences' }))
  await screen.findByText(/USD is your display preference/)
  expect(screen.queryByText('12.123456789012')).toBeNull()
  expect(screen.queryByText('USD 1,500.00000000')).toBeNull()
  expect(screen.getByRole('heading', { name: 'Lot evidence' })).toBeTruthy()
  fireEvent.change(screen.getByLabelText('Amount privacy'), { target: { value: 'visible' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save preferences' }))
  await screen.findByText('12.123456789012')
  expect(screen.getByText('USD 1,500.00000000')).toBeTruthy()
  expect(screen.getByText('INR 2,500.00')).toBeTruthy()
  expect(fetchMock.mock.calls.filter(([path]) => String(path).startsWith('/api/v1/finance/'))).toHaveLength(reads)
})
it('inspects correction history without retaining earlier pages or claiming financial effects', async () => {
  await openObservations()
  fireEvent.click(screen.getByRole('button', { name: `Inspect revisions for observation ${id(30)}` }))
  await screen.findByRole('heading', { name: 'Observation revision history' })
  expect(screen.getByText('15.0000')).toBeTruthy()
  expect(screen.getByText(/Earlier retained revision · Original evidence/)).toBeTruthy()
  expect(screen.queryByText('0.000000000000')).toBeNull()
  const request = fetchMock.mock.calls.find(([path]) => path === '/api/v1/finance/lots/observations/history')!
  expect(request[1]).toMatchObject({ method: 'POST', credentials: 'same-origin', mode: 'same-origin', redirect: 'error', cache: 'no-store', body: JSON.stringify({ id: id(30), limit: 25, before: null }), headers: expect.objectContaining({ 'X-Workspace-Context': 'b'.repeat(64) }) })
  fireEvent.click(screen.getByRole('button', { name: 'Back to current observations' }))
  await screen.findByRole('heading', { name: 'Remaining-lot observation' })
  expect(screen.queryByText('15.0000')).toBeNull()
})
it.each(['light', 'dark'])('masks all monetary/quantity evidence and accessible text in %s mode', async appearance => {
  theme = appearance; masked = true
  const storage = vi.spyOn(Storage.prototype, 'setItem')
  await openObservations()
  expect(document.body.textContent).not.toMatch(/12\.123456789012|1,500|2,500|325\.123|0\.000000/)
  expect(screen.getAllByText('••••').length).toBeGreaterThan(0)
  for (const element of document.querySelectorAll('[aria-label], [title], [aria-valuetext]')) expect(element.outerHTML).not.toMatch(/12\.123456789012|1,500|325\.123/)
  expect(document.querySelector('.wi-lots svg[role=img], .wi-lots progress, .wi-lots meter')).toBeNull()
  expect(storage).not.toHaveBeenCalled()
  expect((await axe.run(document.querySelector('.wi-lots')!, { rules: { 'color-contrast': { enabled: false }, region: { enabled: false } } })).violations).toEqual([])
})
it('replaces pages of lot identities, observations and revisions using bounded cursors', async () => {
  override('/api/v1/finance/lots/query', body => body.after ? { items: [lot], next_after: null } : { items: Array.from({ length: 25 }, (_, n) => ({ ...lot, id: id(n + 100).replace('71000000', '70000000') })), next_after: id(124).replace('71000000', '70000000') })
  await openLots(); fireEvent.click(screen.getByRole('button', { name: 'Next lots' }))
  await screen.findByRole('button', { name: `Inspect observations for lot ${lot.id}` })
  expect(screen.queryByRole('heading', { name: `Lot ${id(100).replace('71000000', '70000000')}` })).toBeNull()
  override('/api/v1/finance/lots/observations/query', body => body.after ? { items: [observation(225)], next_after: null } : { items: Array.from({ length: 25 }, (_, n) => observation(n + 200)), next_after: id(224) })
  fireEvent.click(screen.getByRole('button', { name: `Inspect observations for lot ${lot.id}` }))
  fireEvent.click(await screen.findByRole('button', { name: 'Next observations' }))
  await screen.findByRole('button', { name: `Inspect revisions for observation ${id(225)}` })
  expect(screen.queryByRole('button', { name: `Inspect revisions for observation ${id(200)}` })).toBeNull()
  override('/api/v1/finance/lots/observations/history', body => body.before ? { items: [{ ...observation(225), revision: 1, is_current: false, correction_reason: null, components: [quantity('9.00')] }], next_before: null } : { items: Array.from({ length: 25 }, (_, n) => ({ ...observation(225), revision: 26 - n, is_current: n === 0 })), next_before: 2 })
  fireEvent.click(screen.getByRole('button', { name: `Inspect revisions for observation ${id(225)}` }))
  fireEvent.click(await screen.findByRole('button', { name: 'Earlier revisions' }))
  await screen.findByText('9.00')
  expect(screen.queryByText('12.123456789012')).toBeNull()
})
it('shows absent identities and observations as unknown rather than a zero holding', async () => {
  override('/api/v1/finance/lots/query', () => ({ items: [], next_after: null }))
  await openLots(); expect(screen.getByText(/Missing evidence does not mean zero holdings/)).toBeTruthy()
  override('/api/v1/finance/lots/query', () => ({ items: [lot], next_after: null }))
  fireEvent.click(screen.getByRole('button', { name: 'Refresh lots' }))
  override('/api/v1/finance/lots/observations/query', () => ({ items: [], next_after: null }))
  fireEvent.click(await screen.findByRole('button', { name: `Inspect observations for lot ${lot.id}` }))
  await screen.findByText(/Acquisition and remaining quantities are unknown/)
})
it('clears earlier amounts on unavailable reads and never displays private server errors', async () => {
  await openObservations()
  override('/api/v1/finance/lots/observations/history', () => ({ message: 'private source value' }), 409)
  fireEvent.click(screen.getByRole('button', { name: `Inspect revisions for observation ${id(30)}` }))
  await screen.findByRole('alert')
  expect(screen.queryByText('12.123456789012')).toBeNull()
  expect(screen.queryByText('private source value')).toBeNull()
  expect(auth.snapshot().screen.kind).toBe('workspace')
})
it.each(['lot', 'observation', 'history'])('locks the workspace on mismatched %s scope', async kind => {
  if (kind === 'lot') {
    override('/api/v1/finance/lots/query', () => ({ items: [{ ...lot, position_id: id(90) }], next_after: null }))
    render(<Workspace controller={auth} />); await screen.findByRole('heading', { name: 'A fresh start.' })
    await act(async () => auth.finance('/lots/query', { position_id: position.id, limit: 25 }, value => lotPage(value, position)))
  } else {
    await openLots()
    if (kind === 'observation') override('/api/v1/finance/lots/observations/query', () => ({ items: [{ ...observation(), lot_id: id(90) }], next_after: null }))
    fireEvent.click(screen.getByRole('button', { name: `Inspect observations for lot ${lot.id}` }))
    if (kind === 'history') {
      fireEvent.click(await screen.findByRole('button', { name: `Inspect revisions for observation ${id(30)}` }))
      // The initial valid history can be read; a mismatched subsequent reload must lock.
      await screen.findByRole('heading', { name: 'Observation revision history' })
      fireEvent.click(screen.getByRole('button', { name: 'Back to current observations' }))
      await screen.findByRole('heading', { name: 'Remaining-lot observation' })
      override('/api/v1/finance/lots/observations/history', () => ({ items: [{ ...observation(), id: id(90) }], next_before: null }))
      fireEvent.click(screen.getByRole('button', { name: `Inspect revisions for observation ${id(30)}` }))
    }
  }
  await screen.findByRole('heading', { name: 'Unable to verify this response.' })
  expect(auth.snapshot().screen).toMatchObject({ kind: 'blocked', reason: 'protocol' })
  expect(screen.queryByRole('heading', { name: 'Lot evidence' })).toBeNull()
  expect(screen.queryByText('12.123456789012')).toBeNull()
})
it('discards an in-flight private response after workspace lock', async () => {
  await openLots(); let finish!: (value: Response) => void
  const original = fetchMock.getMockImplementation()!
  fetchMock.mockImplementation((path, options) => path === '/api/v1/finance/lots/observations/query' ? new Promise(resolve => { finish = resolve }) : original(path, options))
  fireEvent.click(screen.getByRole('button', { name: `Inspect observations for lot ${lot.id}` }))
  await screen.findByText('Checking saved lot evidence…')
  await act(async () => { auth.lock(); finish(response({ items: [observation()], next_after: null })) })
  expect(screen.queryByText('12.123456789012')).toBeNull()
  expect(screen.queryByRole('heading', { name: 'Lot evidence' })).toBeNull()
})
