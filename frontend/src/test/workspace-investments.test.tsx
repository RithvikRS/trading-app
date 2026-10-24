import { act, fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import axe from 'axe-core'
import Workspace from '../../workspace/src/Workspace'
import { AuthController } from '../../workspace/src/auth'
import { exactValue, inspection, investment, page, sourceObservation } from '../../workspace/src/investments'

const id = (n: number) => `60000000-0000-4000-8000-${String(n).padStart(12, '0')}`
const security = { id: id(3), name: 'Synthetic Global Equity', isin: 'ZZ0000000016', asset_class: 'equity', fund_scheme_id: null, fund_plan: null, fund_option: null, fund_currency: null }
const identity = { id: id(2), account_id: id(1), instrument_id: id(3), holding_form: 'custody', account_state: 'active' }
const values = [{ role: 'quantity', source: '0.123456789012', currency: null, missing_reason: null }, { role: 'unit_price', source: '325.12345678', currency: 'USD', missing_reason: null }]
const evidence = { id: id(4), revision: 1, account_id: id(1), position_id: id(2), instrument_id: id(3), currency: null, source_id: id(5), coverage: 'snapshot', as_of_date: '2026-10-24', as_of_instant: null, snapshot_scope: 'selected_position', components: values, status: 'active', is_current: true, account_state: 'active' }
const selection = { id: id(6), revision: 1, account_id: id(1), position_id: id(2), currency: null, snapshot_id: id(4), snapshot_revision: 1, reason: 'reviewed', is_current: true }
const holding = { ...identity, instrument: security, choices: [{ selection, state: 'selected', snapshot: evidence }] }
const batch = { id: id(7), revision: 1, source_id: id(5), observation_id: id(9), is_current: true, source_current: true, normalizer: 'synthetic', normalizer_version: '1', contract_version: 1, cash_date_basis: null, row_count: 1 }
const row = { id: id(8), batch_id: id(7), occurrence: 1, kind: 'position_snapshot', instrument_identifier_id: id(10), as_of_date: '2026-10-24', as_of_instant: null, components: values, status: 'reviewable', issue: null, decision: null }
const received = { batch, account_id: id(1), account_mapping_revision: 1, rows: [row], mappings: [{ row_id: id(8), instrument_id: id(3), listing_id: id(11), revision: 1 }], receipt: null }
const saved = { id: id(12), batch_id: id(7), batch_revision: 1, mode: 'limited', coverage: 'snapshot', created_at: '2026-10-24T12:00:00Z', row_count: 1, selection_count: 0, scope_count: 0 }
const account = { id: id(1), kind: 'brokerage', institution: 'indmoney', market: 'US', label: 'Synthetic US account', currencies: ['USD'], revision: 1, state: 'active' }
const observation = (n = 20) => ({ id: id(n), source_id: id(5), previous_id: null, is_current: true, coverage: 'snapshot', period_start: '2026-10-01', period_end: '2026-10-24' })
const session = () => ({ status: 'authenticated', workspace_context: 'a'.repeat(64), expires_at: new Date(Date.now() + 28_800_000).toISOString(), idle_expires_at: new Date(Date.now() + 900_000).toISOString(), fresh_until: new Date(Date.now() + 300_000).toISOString(), factors: [id(99)], unverified_factors: [] })
const response = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store', Date: new Date().toUTCString() } })
const fetchMock = vi.fn<typeof fetch>()
let auth: AuthController, masked: boolean, theme: string, currency: string, included: boolean, completed: boolean
beforeEach(() => {
  masked = true; theme = 'light'; currency = 'INR'; included = false; completed = false
  document.cookie = 'trading_dev_csrf=synthetic-csrf-value-long-enough; Path=/'
  vi.stubGlobal('fetch', fetchMock); fetchMock.mockReset(); auth = new AuthController()
  fetchMock.mockImplementation(async (path, options) => {
    if (path === '/api/v1/auth/bootstrap') return response({ status: 'ready', recovery_email_enabled: false })
    if (path === '/api/v1/auth/session') return response(session())
    if (path === '/api/v1/preferences') { if (options?.method === 'PUT') { const body = JSON.parse(String(options.body)); masked = body.amount_masked; theme = body.theme; currency = body.display_currency } return response({ theme, display_currency: currency, amount_masked: masked, revision: 1 }) }
    if (path === '/api/v1/finance/accounts/query') return response({ items: [account], next_after: null })
    if (path === '/api/v1/finance/investments/query') return response({ items: [holding], next_after: null })
    if (path === '/api/v1/finance/imports/observations/query') return response({ items: [observation(), { ...observation(21), coverage: 'partial_activity', is_current: false }, { ...observation(22), coverage: 'complete_activity', previous_id: id(21) }], next_after: null })
    if (path === '/api/v1/finance/snapshot-review/query') return response({ items: [batch], next_after: null })
    if (path === '/api/v1/finance/snapshot-review/inspect') return response({ ...received, rows: [{ ...row, status: included ? 'included' : 'reviewable', decision: included ? { id: id(8), revision: 1, is_current: true } : null }], receipt: completed ? saved : null })
    if (path === '/api/v1/finance/instruments/query') return response({ items: [security], next_after: null })
    if (path === '/api/v1/finance/positions/query') return response({ items: [identity], next_after: null })
    if (path === '/api/v1/finance/snapshots/query' || path === '/api/v1/finance/snapshots/selections/query') return response({ items: [], next_after: null })
    if (path === '/api/v1/finance/snapshot-review/decide') { included = true; return response({ status: 'saved' }) }
    if (path === '/api/v1/finance/snapshot-review/preview') return response({ token: 'synthetic-preview', batch_id: id(7), batch_revision: 1, row_count: 1, selection_count: 0, coverage: 'snapshot', expires_in: 300 })
    if (path === '/api/v1/finance/snapshot-review/complete') { completed = true; return response(saved) }
    return response({}, 404)
  })
})
afterEach(() => { auth.lock(); vi.unstubAllGlobals(); document.cookie = 'trading_dev_csrf=; Max-Age=0; Path=/'; delete document.documentElement.dataset.theme })
async function open() { render(<Workspace controller={auth} />); await screen.findByRole('heading', { name: 'A fresh start.' }); fireEvent.click(within(screen.getByRole('navigation', { name: 'Workspace navigation' })).getByRole('button', { name: 'Investments' })); await screen.findByRole('heading', { name: 'Your investments' }) }
async function loadHoldings() { await open(); fireEvent.click(screen.getByRole('button', { name: 'Choose an account' })); await screen.findByLabelText('Saved account'); fireEvent.change(screen.getByLabelText('Saved account'), { target: { value: id(1) } }); fireEvent.click(screen.getByRole('button', { name: 'View positions' })); await screen.findByText(security.name) }

it('preserves exact decimal lexemes, explicit source dates, and absent values', () => {
  expect(investment(holding).choices[0]!.snapshot!.components[0]!.source).toBe('0.123456789012')
  expect(exactValue({ role: 'quantity', source: '123456789012345678.123456789012', currency: null, missing_reason: null }, false)).toBe('123,456,789,012,345,678.123456789012')
  expect(exactValue({ role: 'unit_price', source: null, currency: 'USD', missing_reason: 'not_supplied' }, false)).toBe('Unavailable · not supplied')
  expect(inspection(received).rows).toHaveLength(1)
})
it.each([
  { choices: [{ selection, state: 'stale', snapshot: evidence }] },
  { choices: [{ selection, state: 'selected', snapshot: { ...evidence, is_current: false } }] },
  { choices: [{ selection, state: 'selected', snapshot: { ...evidence, position_id: id(90) } }] },
  { choices: [{ selection, state: 'selected', snapshot: { ...evidence, components: [{ ...values[0], source: 0.123 }] } }] },
  { instrument: { ...security, id: id(90) } },
])('rejects inconsistent or inexact investment responses %#', changes => { expect(() => investment({ ...holding, ...changes })).toThrow() })
it('masks every financial value in both list and detail, without browser storage', async () => {
  const storage = vi.spyOn(Storage.prototype, 'setItem')
  await loadHoldings()
  expect(screen.queryByText('0.123456789012')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: /Synthetic Global Equity/ }))
  expect(screen.getByText(/snapshot coverage/)).toBeTruthy()
  expect(screen.queryByText('USD 325.12345678')).toBeNull()
  expect(storage).not.toHaveBeenCalled()
  await act(async () => auth.lock())
  expect(screen.queryByText(security.name)).toBeNull()
})
it.each(['INR', 'USD'])('keeps native USD prices and exact quantities with %s preference', async display => {
  masked = false; currency = display; await loadHoldings()
  expect(screen.getByText('0.123456789012')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: /Synthetic Global Equity/ }))
  expect(screen.getByText('USD 325.12345678')).toBeTruthy()
  expect(screen.getByText(new RegExp(`${display} is your display preference`))).toBeTruthy()
})
it('requires whole-batch review and an explicit position before preview and receipt', async () => {
  const user = userEvent.setup(); await open()
  await user.click(screen.getByRole('button', { name: 'Review snapshots' })); await user.click(await screen.findByRole('button', { name: /Snapshot batch/ }))
  expect((await screen.findByRole('button', { name: 'Preview entire batch' })).hasAttribute('disabled')).toBe(true)
  await user.click(screen.getByRole('button', { name: 'Include row' }))
  await screen.findByLabelText('Explicit position')
  expect(screen.getByRole('button', { name: 'Preview entire batch' }).hasAttribute('disabled')).toBe(true)
  await user.selectOptions(screen.getByLabelText('Explicit position'), id(2))
  await user.click(screen.getByRole('button', { name: 'Preview entire batch' }))
  expect(await screen.findByRole('heading', { name: 'Ready to save this review' })).toBeTruthy()
  const call = fetchMock.mock.calls.find(([path]) => path === '/api/v1/finance/snapshot-review/preview')!
  expect(JSON.parse(String(call[1]!.body)).rows).toEqual([expect.objectContaining({ row_id: id(8), position_id: id(2), review_revision: 1, select: false })])
  await user.click(screen.getByRole('button', { name: 'Complete snapshot review' }))
  expect(await screen.findByRole('heading', { name: 'Snapshot review completed' })).toBeTruthy()
  expect(screen.queryByRole('button', { name: 'Preview entire batch' })).toBeNull()
})
it('rejects late private responses after locking and preserves the same-origin request boundary', async () => {
  await auth.bootstrap(); let resolve!: (value: Response) => void
  fetchMock.mockImplementationOnce(() => new Promise(done => { resolve = done }))
  const reading = auth.finance('/investments/query', { account_id: id(1) }, value => page(value, investment))
  expect(fetchMock.mock.calls.at(-1)?.[1]).toMatchObject({ credentials: 'same-origin', mode: 'same-origin', redirect: 'error', cache: 'no-store', headers: expect.objectContaining({ 'X-Workspace-Context': 'a'.repeat(64) }) })
  auth.lock(); resolve(response({ items: [holding], next_after: null })); expect(await reading).toBeUndefined()
})
it('discards previous amounts on request failure and never renders a server error', async () => {
  masked = false; await loadHoldings()
  fetchMock.mockResolvedValueOnce(response({ error: 'private provider details' }, 409))
  fireEvent.click(screen.getByRole('button', { name: 'Refresh evidence' }))
  expect((await screen.findByRole('alert')).textContent).toContain('Evidence could not be verified')
  expect(screen.queryByText('0.123456789012')).toBeNull()
  expect(screen.queryByText('private provider details')).toBeNull()
  expect(auth.snapshot().screen.kind).toBe('workspace')
})
it.each(['light', 'dark'])('has accessible investment details in %s mode', async appearance => {
  theme = appearance; masked = false; await loadHoldings(); fireEvent.click(screen.getByRole('button', { name: /Synthetic Global Equity/ }))
  expect((await axe.run(document.querySelector('.workspace')!, { runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21aa'] } })).violations).toEqual([])
})

it.each([
  { coverage: 'verified' }, { period_start: null }, { period_end: '2026-09-01' },
  { period_start: '2026-02-30' }, { is_current: 'true' }, { previous_id: id(20) },
])('rejects invalid source-history claims and dates %#', changes => {
  expect(() => sourceObservation({ ...observation(), ...changes })).toThrow()
})
it('keeps unknown undated coverage distinct from an empty period', () => {
  expect(sourceObservation({ ...observation(), coverage: 'unknown', period_start: null, period_end: null })).toMatchObject({ coverage: 'unknown', period_start: null, period_end: null })
  expect(() => sourceObservation({ ...observation(), coverage: 'complete_activity', period_start: null, period_end: null })).toThrow()
})
async function openHistory() { await loadHoldings(); fireEvent.click(screen.getByRole('button', { name: /Synthetic Global Equity/ })); fireEvent.click(screen.getByRole('button', { name: 'Inspect source-history coverage' })); await screen.findByRole('heading', { name: 'Source-history coverage' }) }
it('shows source coverage claims and replacements without implying completed history', async () => {
  masked = false; await openHistory()
  expect(screen.getByRole('heading', { name: 'Holdings snapshot only' })).toBeTruthy()
  expect(screen.getByRole('heading', { name: 'Partial activity reported' })).toBeTruthy()
  expect(screen.getByRole('heading', { name: 'Source claims complete activity' })).toBeTruthy()
  expect(screen.getByText('Superseded evidence')).toBeTruthy()
  expect(screen.getByText(/It does not prove a completed import/)).toBeTruthy()
  expect(screen.queryByText('0.123456789012')).toBeNull()
  expect(fetchMock.mock.calls.at(-1)).toEqual(['/api/v1/finance/imports/observations/query', expect.objectContaining({ method: 'POST', body: JSON.stringify({ source_id: id(5), after: null, limit: 25 }), headers: expect.objectContaining({ 'X-Workspace-Context': 'a'.repeat(64) }) })])
  expect((await axe.run(document.querySelector('.workspace')!, { rules: { 'color-contrast': { enabled: false } } })).violations).toEqual([])
})
it('paginates source evidence without retaining earlier periods or issuing mutations', async () => {
  const original = fetchMock.getMockImplementation()!
  fetchMock.mockImplementation((path, options) => path === '/api/v1/finance/imports/observations/query' ? Promise.resolve(response(JSON.parse(String(options!.body)).after ? { items: [{ ...observation(125), period_start: null, period_end: null, coverage: 'unknown' }], next_after: null } : { items: Array.from({ length: 25 }, (_, index) => observation(100 + index)), next_after: id(124) })) : original(path, options))
  await openHistory(); fireEvent.click(screen.getByRole('button', { name: 'Next evidence page' }))
  await screen.findByRole('heading', { name: 'Coverage unknown' })
  expect(screen.queryByText(id(100))).toBeNull()
  expect(screen.getByText('Not supplied')).toBeTruthy()
  expect(fetchMock.mock.calls.some(([path]) => String(path).includes('/snapshot-review/'))).toBe(false)
})
it('locks on mismatched source scope instead of attaching another source to the view', async () => {
  const original = fetchMock.getMockImplementation()!
  fetchMock.mockImplementation((path, options) => path === '/api/v1/finance/imports/observations/query' ? Promise.resolve(response({ items: [{ ...observation(), source_id: id(90) }], next_after: null })) : original(path, options))
  await loadHoldings(); fireEvent.click(screen.getByRole('button', { name: /Synthetic Global Equity/ })); fireEvent.click(screen.getByRole('button', { name: 'Inspect source-history coverage' }))
  await screen.findByLabelText('Email address')
  expect(screen.queryByText(id(90))).toBeNull()
  expect(screen.queryByRole('heading', { name: 'Source-history coverage' })).toBeNull()
})
