import { act, fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import axe from 'axe-core'
import Workspace from '../../workspace/src/Workspace'
import { AuthController } from '../../workspace/src/auth'
import { activityCoveragePage, activityHistory, activityPage, eventEvidence, eventIdentity } from '../../workspace/src/activity-evidence'

const id = (n: number) => `72000000-0000-4000-8000-${String(n).padStart(12, '0')}`
const position = { id: id(2), account_id: id(1), instrument_id: id(3), holding_form: 'custody', account_state: 'active' }
const security = { id: id(3), name: 'Saved employee-share instrument', isin: 'ZZ0000000016', asset_class: 'equity', fund_scheme_id: null, fund_plan: null, fund_option: null, fund_currency: null }
const account = { id: id(1), kind: 'employee_stock', institution: 'ubs', market: 'US', label: 'Employee shares', currencies: ['INR', 'USD'], revision: 1, state: 'active' }
const quantity = (source = '12.123456789012') => ({ role: 'quantity', source, currency: null, missing_reason: null })
const cash = (source = '-1500.00', currency = 'USD') => ({ role: 'net_cash', source, currency, missing_reason: null })
const components = [quantity(), cash(), { role: 'unit_price', source: '325.123456789012', currency: 'USD', missing_reason: null }, { role: 'fee', source: null, currency: 'USD', missing_reason: 'not_supplied' }, { role: 'withholding', source: '0.00000000', currency: 'USD', missing_reason: null }]
const event = (n = 30) => ({
  id: id(n), account_id: id(1), position_id: id(2), instrument_id: id(3), kind: 'buy', revision: 2, is_current: true, account_state: 'active', status: 'active', posting_state: 'posted', correction_reason: 'source_correction',
  trade_date: '2026-05-01', settlement_date: '2026-05-03', booking_date: '2026-05-04', value_date: '2026-05-05',
  source_row_id: id(10), source_review_revision: 1, source_id: id(11), observation_id: id(12), batch_id: id(13), coverage: 'partial_activity', period_start: '2026-05-01', period_end: '2026-05-31', cash_date_basis: 'settlement', components,
})
const otherPosition = () => ({ ...event(31), kind: 'sell', position_id: id(22), instrument_id: id(23), components: [quantity('-0.005000000000'), cash('25.25')] })
const pendingCash = () => ({ ...event(32), kind: 'cash_movement', position_id: null, instrument_id: null, posting_state: 'pending', trade_date: null, settlement_date: null, value_date: null, cash_date_basis: 'booking', components: [cash('0.00', 'INR')] })
const cancelled = () => ({ ...event(33), status: 'cancelled', posting_state: 'pending', correction_reason: 'cancellation', components: [], trade_date: null, settlement_date: null, value_date: null })
const newer = () => ({ ...event(), revision: 3, source_row_id: id(110), source_id: id(111), observation_id: id(112), batch_id: id(113), source_review_revision: 4, coverage: 'snapshot', period_start: '2026-09-01', period_end: '2026-09-30', trade_date: '2026-09-02', settlement_date: '2026-09-03', booking_date: '2026-09-04', value_date: '2026-09-05', cash_date_basis: 'value', components: [quantity('13.0000'), cash('-1600.00')] })
const source = (n = 60, sourceId = id(11)) => ({ id: id(n), source_id: sourceId, previous_id: null, is_current: true, coverage: 'partial_activity', period_start: '2026-05-01', period_end: '2026-05-31' })
const session = () => ({ status: 'authenticated', workspace_context: 'c'.repeat(64), expires_at: new Date(Date.now() + 28_800_000).toISOString(), idle_expires_at: new Date(Date.now() + 900_000).toISOString(), fresh_until: new Date(Date.now() + 300_000).toISOString(), factors: [id(99)], unverified_factors: [] })
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
    if (path === '/api/v1/finance/accounts/query') return response({ items: [account], next_after: null })
    if (path === '/api/v1/finance/investments/query') return response({ items: [{ ...position, instrument: security, choices: [] }], next_after: null })
    if (path === '/api/v1/finance/events/query') return response({ items: [event(), otherPosition(), pendingCash(), cancelled()], next_after: null })
    if (path === '/api/v1/finance/events/history') return response({ items: [newer(), { ...event(), is_current: false }, { ...event(), revision: 1, is_current: false, correction_reason: null, posting_state: 'pending', components: [quantity('15.0000'), cash('-1400.00')] }], next_before: null })
    if (path === '/api/v1/finance/imports/observations/query') { const sourceId = JSON.parse(String(options!.body)).source_id; return response({ items: [source(60, sourceId), { ...source(61, sourceId), is_current: false }, { ...source(62, sourceId), previous_id: id(61), coverage: 'complete_activity' }], next_after: null }) }
    return response({}, 404)
  })
})
afterEach(() => { auth.lock(); vi.unstubAllGlobals(); document.cookie = 'trading_dev_csrf=; Max-Age=0; Path=/'; delete document.documentElement.dataset.theme })
async function openDetail() {
  render(<Workspace controller={auth} />); await screen.findByRole('heading', { name: 'A fresh start.' })
  fireEvent.click(within(screen.getByRole('navigation', { name: 'Workspace navigation' })).getByRole('button', { name: 'Investments' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Choose an account' }))
  fireEvent.change(await screen.findByLabelText('Saved account'), { target: { value: account.id } })
  fireEvent.click(screen.getByRole('button', { name: 'View positions' }))
  fireEvent.click(await screen.findByRole('button', { name: /Saved employee-share instrument/ }))
}
async function openActivity() { await openDetail(); fireEvent.click(screen.getByRole('button', { name: 'Inspect account activity' })); await screen.findByRole('heading', { name: 'Account activity' }) }
async function openHistory() { await openActivity(); fireEvent.click(screen.getByRole('button', { name: `Inspect revisions for event ${id(30)}` })); await screen.findByRole('heading', { name: 'Event revision history' }) }
function override(path: string, handler: (body: Record<string, unknown>) => unknown, status = 200) {
  const original = fetchMock.getMockImplementation()!
  fetchMock.mockImplementation((url, options) => url === path ? Promise.resolve(response(handler(JSON.parse(String(options!.body))), status)) : original(url, options))
}

it('preserves signed source lexemes, independent dates, zero cash and explicit pending/cancelled state', () => {
  expect(eventEvidence(event(), account.id).components).toEqual(components)
  expect(eventEvidence(otherPosition(), account.id).components[0]!.source).toBe('-0.005000000000')
  expect(eventEvidence(pendingCash(), account.id)).toMatchObject({ posting_state: 'pending', position_id: null, components: [cash('0.00', 'INR')] })
  expect(eventEvidence(cancelled(), account.id)).toMatchObject({ posting_state: 'pending', status: 'cancelled', components: [] })
})
it.each([
  { account_id: id(90) }, { id: 'not-an-id' }, { position_id: null }, { position_id: null, instrument_id: null },
  { kind: 'position_snapshot' }, { posting_state: 'settled' }, { account_state: 'closed' }, { is_current: 'true' }, { revision: true }, { revision: 0 }, { revision: Number.MAX_SAFE_INTEGER + 1 },
  { revision: 1 }, { correction_reason: null }, { correction_reason: 'cancellation' }, { status: 'cancelled' }, { correction_reason: 'posting_update', posting_state: 'pending' },
  { trade_date: null }, { trade_date: '0000-01-01' }, { settlement_date: '2026-02-30' }, { value_date: '2026-05-01T12:00:00Z' },
  { coverage: 'verified' }, { period_start: null }, { period_end: '2026-04-01' }, { cash_date_basis: 'trade' }, { source_review_revision: false },
  { components: [] }, { components: [cash()] }, { components: [quantity()] }, { components: [quantity(), cash(), cash()] },
  { components: [quantity('0.00'), cash()] }, { components: [quantity('-1'), cash()] }, { components: [quantity(), cash('0.00')] }, { components: [quantity(), cash('1.00')] },
  { components: [{ ...quantity(), source: 1.25 }, cash()] }, { components: [quantity('1e2'), cash()] }, { components: [quantity(), cash('-1.001')] },
  { components: [{ ...quantity(), currency: 'USD' }, cash()] }, { components: [quantity(), { ...cash(), currency: null }] },
  { components: [quantity(), cash(), { role: 'fee', source: '1.00', currency: 'INR', missing_reason: null }] },
  { components: [quantity(), cash(), { role: 'unit_price', source: '0', currency: 'USD', missing_reason: null }] },
  { components: [quantity(), cash(), { role: 'acquisition_cost', source: '1', currency: 'USD', missing_reason: null }] },
  { components: [quantity(), cash(), { role: 'fee', source: null, currency: 'USD', missing_reason: null }] },
  { components: [{ ...quantity(), description: 'unexpected' }, cash()] }, { provider_reference: 'unexpected' },
])('rejects malformed or inconsistent activity evidence %#', changes => { expect(() => eventEvidence({ ...event(), ...changes }, account.id)).toThrow() })
it('enforces event-kind roles and signs without rejecting independent event currencies', () => {
  for (const kind of ['fee', 'withholding', 'dividend', 'cash_movement']) expect(eventEvidence({ ...event(), kind, components: [cash(kind === 'dividend' ? '0.00' : '-0.00')] }, account.id).kind).toBe(kind)
  expect(() => eventEvidence({ ...event(), kind: 'fee', components: [cash('1.00')] }, account.id)).toThrow()
  expect(() => eventEvidence({ ...otherPosition(), components: [quantity('1'), cash('1.00')] }, account.id)).toThrow()
  expect(() => eventEvidence({ ...cancelled(), components: [cash()] }, account.id)).toThrow()
  expect(() => eventEvidence({ ...cancelled(), booking_date: null }, account.id)).toThrow()
  expect(() => eventEvidence({ ...pendingCash(), booking_date: null }, account.id)).toThrow()
})
it('binds history identity while allowing a newer revision with changed source, period, dates and values', () => {
  const clicked = eventEvidence(event(), account.id), root = eventIdentity(clicked)
  const result = activityHistory({ items: [newer(), { ...event(), is_current: false }], next_before: null }, root)
  expect(result.items[0]).toMatchObject({ revision: 3, source_id: id(111), period_start: '2026-09-01', trade_date: '2026-09-02', cash_date_basis: 'value' })
  for (const changes of [{ id: id(90) }, { account_id: id(90) }, { position_id: id(90) }, { instrument_id: id(90) }, { kind: 'subscription' }]) expect(() => activityHistory({ items: [{ ...newer(), ...changes }], next_before: null }, root)).toThrow()
  expect(() => activityHistory({ items: [newer(), { ...event(), revision: 4, is_current: false }], next_before: null }, root)).toThrow()
  expect(() => activityHistory({ items: [newer()], next_before: 3 }, root)).toThrow()
  expect(() => activityHistory({ items: [newer()], next_before: null }, root, 3)).toThrow()
  expect(() => activityHistory({ items: [newer()], next_before: '3' }, root)).toThrow()
})
it('requires exact page fields, current rows and bounded nonrepeating cursors', () => {
  const valid = { items: [event()], next_after: null }
  expect(() => activityPage({ ...valid, total: 10 }, position)).toThrow()
  expect(() => activityPage({ items: [{ ...event(), is_current: false }], next_after: null }, position)).toThrow()
  expect(() => activityPage({ items: [event(), event()], next_after: null }, position)).toThrow()
  expect(() => activityPage({ ...valid, next_after: id(30) }, position)).toThrow()
  expect(() => activityPage(valid, position, id(30))).toThrow()
  expect(() => activityPage({ items: Array.from({ length: 26 }, (_, n) => event(100 + n)), next_after: null }, position)).toThrow()
  for (const changes of [{ source_id: id(90) }, { period_start: '0000-01-01' }, { previous_id: id(60) }, { coverage: 'verified' }, { private_reference: 'unexpected' }]) expect(() => activityCoveragePage({ items: [{ ...source(), ...changes }], next_after: null }, id(11))).toThrow()
  expect(activityCoveragePage({ items: [{ ...source(), coverage: 'unknown', period_start: null, period_end: null }], next_after: null }, id(11)).items[0]!.period_start).toBeNull()
})
it.each(['INR', 'USD'])('shows account-wide native activity with %s preference without filtering other positions or cash', async preference => {
  currency = preference; await openActivity()
  expect(screen.getByText(/Showing all saved events in this account/)).toBeTruthy()
  expect(screen.getByText(/Another position in this account/)).toBeTruthy()
  expect(screen.getByText('Account-level cash or charge')).toBeTruthy()
  expect(screen.getByText('USD -1,500.00')).toBeTruthy()
  expect(screen.getByText('USD 25.25')).toBeTruthy()
  expect(screen.getByText('INR 0.00')).toBeTruthy()
  expect(screen.getByText('-0.005000000000')).toBeTruthy()
  expect(screen.getByText('Pending · Active evidence')).toBeTruthy()
  expect(screen.getByText('Pending · Cancelled evidence')).toBeTruthy()
  expect(screen.getAllByText('2026-05-01').length).toBeGreaterThan(0)
  expect(screen.getAllByText('2026-05-03').length).toBeGreaterThan(0)
  expect(fetchMock.mock.calls.find(([path]) => path === '/api/v1/finance/events/query')?.[1]).toMatchObject({ method: 'POST', mode: 'same-origin', credentials: 'same-origin', redirect: 'error', cache: 'no-store', body: JSON.stringify({ account_id: account.id, limit: 25, after: null }), headers: expect.objectContaining({ 'X-Workspace-Context': 'c'.repeat(64) }) })
})
it('keeps correction, posting and source coverage history separate from account completeness', async () => {
  await openHistory()
  expect(screen.getByText('13.0000')).toBeTruthy(); expect(screen.getByText('15.0000')).toBeTruthy()
  expect(screen.getByText('USD -1,600.00')).toBeTruthy(); expect(screen.getByText('Pending · Active evidence')).toBeTruthy()
  expect(screen.queryByText('INR 0.00')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: `Inspect source coverage for event ${id(30)}, revision 3` }))
  await screen.findByRole('heading', { name: 'Source coverage for event' })
  expect(fetchMock.mock.calls.at(-1)?.[1]?.body).toBe(JSON.stringify({ source_id: id(111), limit: 25, after: null }))
  expect(screen.getByRole('heading', { name: 'Source claims complete activity' })).toBeTruthy()
  expect(screen.getByText('Superseded evidence')).toBeTruthy()
  expect(screen.getByText(/Reconciled completion must be checked separately/)).toBeTruthy()
  expect(screen.queryByText('13.0000')).toBeNull()
})
it('applies saved masking and currency changes to open history without refetching or converting evidence', async () => {
  await openHistory(); const reads = fetchMock.mock.calls.filter(([path]) => String(path).includes('/finance/')).length
  fireEvent.change(screen.getByLabelText('Display currency'), { target: { value: 'USD' } })
  fireEvent.change(screen.getByLabelText('Amount privacy'), { target: { value: 'hidden' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save preferences' }))
  await screen.findByText(/USD is your display preference/)
  expect(document.querySelector('.wi-activity')?.textContent).not.toMatch(/13\.0000|15\.0000|1,500|1,600|1,400|325\.123|Unavailable · not supplied/)
  for (const element of document.querySelectorAll('.wi-activity [aria-label], .wi-activity [title], .wi-activity [aria-valuetext]')) expect(element.outerHTML).not.toMatch(/13\.0000|15\.0000|1,500|1,600/)
  fireEvent.change(screen.getByLabelText('Amount privacy'), { target: { value: 'visible' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save preferences' }))
  await screen.findByText('USD -1,600.00')
  expect(fetchMock.mock.calls.filter(([path]) => String(path).includes('/finance/'))).toHaveLength(reads)
})
it.each(['light', 'dark'])('masks zero and missing current values without geometry or browser storage in %s mode', async appearance => {
  masked = true; theme = appearance; const storage = vi.spyOn(Storage.prototype, 'setItem')
  await openActivity(); expect(document.querySelector('.wi-activity')?.textContent).not.toMatch(/12\.123|1,500|25\.25|0\.00|325\.123|Unavailable · not supplied/)
  expect(screen.getAllByText('••••').length).toBeGreaterThan(0)
  expect(document.querySelector('.wi-activity svg[role=img], .wi-activity progress, .wi-activity meter')).toBeNull()
  expect(location.hash).toBe(''); expect(storage).not.toHaveBeenCalled()
  expect((await axe.run(document.querySelector('.wi-activity')!, { rules: { 'color-contrast': { enabled: false }, region: { enabled: false } } })).violations).toEqual([])
})
it('replaces activity pages without dropping unrelated positions', async () => {
  override('/api/v1/finance/events/query', body => body.after ? { items: [event(125)], next_after: null } : { items: Array.from({ length: 25 }, (_, n) => ({ ...otherPosition(), id: id(100 + n) })), next_after: id(124) })
  await openActivity(); fireEvent.click(screen.getByRole('button', { name: 'Next activity page' }))
  await screen.findByRole('button', { name: `Inspect revisions for event ${id(125)}` })
  expect(screen.queryByRole('button', { name: `Inspect revisions for event ${id(100)}` })).toBeNull()
  expect(fetchMock.mock.calls.at(-1)?.[1]?.body).toBe(JSON.stringify({ account_id: id(1), limit: 25, after: id(124) }))
})
it('uses descending history cursors without retaining old pages', async () => {
  override('/api/v1/finance/events/history', body => body.before ? { items: [{ ...event(), revision: 1, is_current: false, correction_reason: null, components: [quantity('99.0000'), cash()] }], next_before: null } : { items: Array.from({ length: 25 }, (_, n) => ({ ...event(), revision: 26 - n, is_current: n === 0 })), next_before: 2 })
  await openHistory(); fireEvent.click(screen.getByRole('button', { name: 'Earlier event revisions' }))
  await screen.findByText('99.0000'); expect(screen.queryByText('12.123456789012')).toBeNull()
  expect(fetchMock.mock.calls.at(-1)?.[1]?.body).toBe(JSON.stringify({ id: id(30), limit: 25, before: 2 }))
})
it('paginates selected-source coverage and preserves unknown undated evidence', async () => {
  override('/api/v1/finance/imports/observations/query', body => body.after ? { items: [{ ...source(125), coverage: 'unknown', period_start: null, period_end: null }], next_after: null } : { items: Array.from({ length: 25 }, (_, n) => source(100 + n)), next_after: id(124) })
  await openActivity(); fireEvent.click(screen.getByRole('button', { name: `Inspect source coverage for event ${id(30)}, revision 2` }))
  fireEvent.click(await screen.findByRole('button', { name: 'Next source page' }))
  await screen.findByRole('heading', { name: 'Coverage unknown' }); expect(screen.queryByText(id(100))).toBeNull()
  expect(fetchMock.mock.calls.at(-1)?.[1]?.body).toBe(JSON.stringify({ source_id: id(11), limit: 25, after: id(124) }))
})
it('shows empty and archived evidence without inventing movements or performing writes', async () => {
  override('/api/v1/finance/events/query', () => ({ items: [], next_after: null }))
  await openActivity(); expect(screen.getByText(/Missing activity does not establish zero movements/)).toBeTruthy()
  override('/api/v1/finance/events/query', () => ({ items: [{ ...event(), account_state: 'archived' }], next_after: null }))
  fireEvent.click(screen.getByRole('button', { name: 'Refresh activity' }))
  await screen.findByText(/Archived account/)
  expect(fetchMock.mock.calls.filter(([path]) => String(path).includes('/finance/')).every(([path]) => /\/(accounts|investments|events)\/query$/.test(String(path)))).toBe(true)
})
it('clears values during a failed read and never renders the private server body', async () => {
  await openActivity()
  override('/api/v1/finance/events/history', () => ({ details: 'private provider response' }), 409)
  fireEvent.click(screen.getByRole('button', { name: `Inspect revisions for event ${id(30)}` }))
  await screen.findByRole('alert')
  expect(screen.queryByText('USD -1,500.00')).toBeNull(); expect(screen.queryByText('private provider response')).toBeNull()
  expect(auth.snapshot().screen.kind).toBe('workspace')
})
it.each(['activity', 'history', 'coverage'])('fails closed on a foreign %s response and clears the view', async kind => {
  await openDetail()
  if (kind === 'activity') override('/api/v1/finance/events/query', () => ({ items: [{ ...event(), account_id: id(90) }], next_after: null }))
  fireEvent.click(screen.getByRole('button', { name: 'Inspect account activity' }))
  if (kind !== 'activity') {
    await screen.findByRole('heading', { name: 'Account activity' })
    if (kind === 'history') { override('/api/v1/finance/events/history', () => ({ items: [{ ...event(), position_id: id(90) }], next_before: null })); fireEvent.click(screen.getByRole('button', { name: `Inspect revisions for event ${id(30)}` })) }
    else { override('/api/v1/finance/imports/observations/query', () => ({ items: [{ ...source(), source_id: id(90) }], next_after: null })); fireEvent.click(screen.getByRole('button', { name: `Inspect source coverage for event ${id(30)}, revision 2` })) }
  }
  await screen.findByRole('heading', { name: 'Unable to verify this response.' })
  expect(auth.snapshot().screen).toMatchObject({ kind: 'blocked', reason: 'protocol' })
  expect(screen.queryByRole('heading', { name: 'Account activity' })).toBeNull(); expect(screen.queryByText('USD -1,500.00')).toBeNull()
})
it.each(['navigate', 'logout', 'lock'])('discards an in-flight activity history after %s', async action => {
  await openActivity(); let finish!: (value: Response) => void
  const original = fetchMock.getMockImplementation()!
  fetchMock.mockImplementation((path, options) => path === '/api/v1/finance/events/history' ? new Promise(resolve => { finish = resolve }) : original(path, options))
  fireEvent.click(screen.getByRole('button', { name: `Inspect revisions for event ${id(30)}` }))
  await screen.findByText('Checking saved account activity…'); expect(screen.queryByText('USD -1,500.00')).toBeNull()
  if (action === 'navigate') fireEvent.click(within(screen.getByRole('navigation', { name: 'Workspace navigation' })).getByRole('button', { name: 'Overview' }))
  else if (action === 'logout') fireEvent.click(screen.getByRole('button', { name: 'Sign out here' }))
  else await act(async () => auth.lock())
  await act(async () => finish(response({ items: [newer()], next_before: null })))
  expect(screen.queryByText('USD -1,600.00')).toBeNull(); expect(screen.queryByRole('heading', { name: 'Account activity' })).toBeNull()
  if (action === 'navigate') expect(screen.getByRole('heading', { name: 'A fresh start.' })).toBeTruthy()
  else await screen.findByLabelText('Email address')
})
it('opens account activity with the keyboard and moves focus to its heading', async () => {
  await openDetail(); const user = userEvent.setup()
  screen.getByRole('button', { name: 'Inspect account activity' }).focus(); await user.keyboard('{Enter}')
  const heading = await screen.findByRole('heading', { name: 'Account activity' }); expect(document.activeElement).toBe(heading)
  await user.tab(); expect(document.activeElement?.textContent).toContain('Refresh activity')
})

it('binds the originating position instrument without restricting account-wide events on any page', () => {
  const rows = [event(), otherPosition(), pendingCash()]
  expect(activityPage({ items: rows, next_after: null }, position).items).toHaveLength(3)
  expect(activityPage({ items: rows, next_after: null }, position, id(29)).items).toHaveLength(3)
  for (const after of [null, id(29)]) expect(() => activityPage({ items: [{ ...event(), instrument_id: id(90) }], next_after: null }, position, after)).toThrow()
})
it('keeps the opened revision as a first-history-page lower bound while allowing older pagination', () => {
  const root = eventIdentity(eventEvidence(event(), account.id))
  const original = { ...event(), revision: 1, correction_reason: null }
  expect(root.revision).toBe(2)
  expect(() => activityHistory({ items: [original], next_before: null }, root)).toThrow()
  expect(activityHistory({ items: [event()], next_before: null }, root).items[0]!.revision).toBe(2)
  expect(activityHistory({ items: [newer()], next_before: null }, root).items[0]!.revision).toBe(3)
  expect(activityHistory({ items: [{ ...original, is_current: false }], next_before: null }, root, 2).items[0]!.revision).toBe(1)
})
it.each(['initial', 'next', 'refresh'])('fails closed when the originating holding instrument changes on the %s activity read', async read => {
  if (read === 'initial') {
    await openDetail()
    override('/api/v1/finance/events/query', () => ({ items: [{ ...event(), instrument_id: id(90) }], next_after: null }))
    fireEvent.click(screen.getByRole('button', { name: 'Inspect account activity' }))
  } else {
    if (read === 'next') override('/api/v1/finance/events/query', body => body.after ? { items: [{ ...event(125), instrument_id: id(90) }], next_after: null } : { items: Array.from({ length: 25 }, (_, n) => ({ ...otherPosition(), id: id(100 + n) })), next_after: id(124) })
    await openActivity()
    if (read === 'refresh') override('/api/v1/finance/events/query', () => ({ items: [{ ...event(), instrument_id: id(90) }], next_after: null }))
    fireEvent.click(screen.getByRole('button', { name: read === 'next' ? 'Next activity page' : 'Refresh activity' }))
  }
  await screen.findByRole('heading', { name: 'Unable to verify this response.' })
  expect(auth.snapshot().screen).toMatchObject({ kind: 'blocked', reason: 'protocol' })
  expect(screen.queryByRole('heading', { name: 'Account activity' })).toBeNull()
  expect(screen.queryByText('USD -1,500.00')).toBeNull()
  expect(screen.queryByText('USD 25.25')).toBeNull()
})
it('fails closed when the live first history page regresses behind the clicked revision', async () => {
  await openActivity()
  override('/api/v1/finance/events/history', () => ({ items: [{ ...event(), revision: 1, correction_reason: null }], next_before: null }))
  fireEvent.click(screen.getByRole('button', { name: `Inspect revisions for event ${id(30)}` }))
  await screen.findByRole('heading', { name: 'Unable to verify this response.' })
  expect(auth.snapshot().screen).toMatchObject({ kind: 'blocked', reason: 'protocol' })
  expect(screen.queryByRole('heading', { name: 'Account activity' })).toBeNull()
  expect(screen.queryByText('USD -1,500.00')).toBeNull()
})