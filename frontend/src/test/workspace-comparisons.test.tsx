import { act, fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import axe from 'axe-core'
import Workspace from '../../workspace/src/Workspace'
import { AuthController } from '../../workspace/src/auth'
import { receiptContext, savedReceipt } from '../../workspace/src/receipt-evidence'
import { nativeComparison, nativeScope, scopePage } from '../../workspace/src/comparison-evidence'
import type { NativeScope } from '../../workspace/src/comparison-evidence'

const id = (n: number) => `73000000-0000-4000-8000-${String(n).padStart(12, '0')}`
const position = { id: id(2), account_id: id(1), instrument_id: id(3), holding_form: 'custody', account_state: 'active' }
const lot = { id: id(4), position_id: id(2), account_id: id(1), instrument_id: id(3), account_state: 'active' }
const security = { id: id(3), name: 'Saved employee-share instrument', isin: 'ZZ0000000016', asset_class: 'equity', fund_scheme_id: null, fund_plan: null, fund_option: null, fund_currency: null }
const account = { id: id(1), kind: 'employee_stock', institution: 'ubs', market: 'US', label: 'Employee shares', currencies: ['INR', 'USD'], revision: 1, state: 'active' }
const quantity = { role: 'quantity', source: '12.123456789012', currency: null, missing_reason: null }
const event = { id: id(30), account_id: id(1), position_id: id(2), instrument_id: id(3), kind: 'buy', revision: 2, is_current: true, account_state: 'active', status: 'active', posting_state: 'posted', correction_reason: 'source_correction', trade_date: '2026-05-01', settlement_date: '2026-05-03', booking_date: '2026-05-04', value_date: '2026-05-05', source_row_id: id(10), source_review_revision: 1, source_id: id(11), observation_id: id(12), batch_id: id(13), coverage: 'complete_activity' as const, period_start: '2026-05-01', period_end: '2026-05-31', cash_date_basis: 'settlement', components: [quantity, { role: 'net_cash', source: '-1500.00', currency: 'USD', missing_reason: null }] }
const observation = { ...lot, id: id(40), lot_id: lot.id, revision: 2, is_current: true, scope: 'lot_acquisition', correction_reason: 'source_correction', status: 'active', components: [quantity], as_of_date: '2026-05-31', acquisition_date: '2026-05-01', booking_date: null, source_row_id: id(15), source_review_revision: 2, source_id: id(11), observation_id: id(12), batch_id: id(13), coverage: 'complete_activity' as const, period_start: '2026-05-01', period_end: '2026-05-31', cash_date_basis: null }
const context = receiptContext('event', event)
const receipt = (n = 80, batch = id(13)) => ({ id: id(n), batch_id: batch, batch_revision: 2, mode: 'reconciled', coverage: 'complete_activity', created_at: '2026-05-31T18:42:10.123456+00:00', row_count: 20, selection_count: 1, scope_count: 3 })
const row = (n = 10) => ({ id: id(n), receipt_id: id(80), review_revision: 1, operation: 'correct', outcome: 'corrected', event_id: id(30), lot_observation_id: null, snapshot_id: null, record_revision: 2, provider_identity_id: null, selection_id: null, selection_revision: null })
const rows = () => [row(), { ...row(14), operation: 'record', outcome: 'linked', event_id: id(31), provider_identity_id: id(71) }, { ...row(15), review_revision: 2, event_id: null, lot_observation_id: id(40) }, { ...row(16), operation: 'record', outcome: 'recorded', event_id: null, snapshot_id: id(50), selection_id: id(72), selection_revision: 3 }, { ...row(17), operation: 'exclude', outcome: 'excluded', event_id: null, record_revision: null }]
const scope = (n = 100, kind: 'cash' | 'units' = 'cash', currency: 'INR' | 'USD' = 'INR'): NativeScope => ({ id: id(n), receipt_id: id(80), kind, account_id: id(n === 101 ? 21 : 1), position_id: kind === 'units' ? id(2) : null, currency: kind === 'cash' ? currency : null, period_start: '2026-05-01', period_end: '2026-05-31', date_basis: kind === 'units' ? 'trade' : 'booking', rule_version: 1, input_count: 9 })
const scopes = () => [scope(), scope(101, 'cash', 'USD'), scope(102, 'units')]
const comparison = (selected = scope()) => ({ scope: selected, source: { outcome: 'balanced', opening: selected.kind === 'cash' ? '1000.00' : '12.123456789012', posted_total: selected.kind === 'cash' ? '-125.50' : '-0.000000000001', closing: selected.kind === 'cash' ? '874.50' : '12.123456789011', calculated_closing: selected.kind === 'cash' ? '874.50' : '12.123456789011', difference: selected.kind === 'cash' ? '0.00' : '0.000000000000', posted_count: 2, pending_count: 1 }, combined: { outcome: 'balanced', opening: selected.kind === 'cash' ? '1000' : '12.123456789012', posted_total: selected.kind === 'cash' ? '-125.5' : '-0.000000000001', closing: selected.kind === 'cash' ? '874.5' : '12.123456789011', calculated_closing: selected.kind === 'cash' ? '874.50' : '12.123456789011', difference: selected.kind === 'cash' ? '-0.00' : '0', posted_count: 1, pending_count: 1 } })
const metadata = (scope_count = 3) => savedReceipt({ ...receipt(), scope_count }, context)
const session = () => ({ status: 'authenticated', workspace_context: 'd'.repeat(64), expires_at: new Date(Date.now() + 28_800_000).toISOString(), idle_expires_at: new Date(Date.now() + 900_000).toISOString(), fresh_until: new Date(Date.now() + 300_000).toISOString(), factors: [id(99)], unverified_factors: [] })
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
    if (path === '/api/v1/finance/events/query') return response({ items: [event], next_after: null })
    if (path === '/api/v1/finance/events/history') return response({ items: [{ ...event, revision: 3, batch_id: id(113), source_row_id: id(110) }, { ...event, is_current: false }], next_before: null })
    if (path === '/api/v1/finance/lots/query') return response({ items: [lot], next_after: null })
    if (path === '/api/v1/finance/lots/observations/query') return response({ items: [observation], next_after: null })
    if (path === '/api/v1/finance/lots/observations/history') return response({ items: [observation, { ...observation, revision: 1, is_current: false, correction_reason: null, batch_id: id(213), source_row_id: id(210) }], next_before: null })
    if (path === '/api/v1/finance/receipts/query') return response({ items: [receipt(80, JSON.parse(String(options!.body)).batch_id)], next_after: null })
    if (path === '/api/v1/finance/receipts/rows/query') return response({ items: rows(), next_after: null })
    if (path === '/api/v1/finance/receipts/scopes/query') return response({ items: scopes(), next_after: null })
    if (path === '/api/v1/finance/receipts/scopes/inspect') return response(comparison(scopes().find(item => item.id === JSON.parse(String(options!.body)).id)!))
    return response({}, 404)
  })
})
afterEach(() => { auth.lock(); vi.unstubAllGlobals(); document.cookie = 'trading_dev_csrf=; Max-Age=0; Path=/'; delete document.documentElement.dataset.theme })
function override(path: string, handler: (body: Record<string, unknown>) => unknown, status = 200) { const original = fetchMock.getMockImplementation()!; fetchMock.mockImplementation((url, options) => url === path ? Promise.resolve(response(handler(JSON.parse(String(options!.body))), status)) : original(url, options)) }
async function openDetail() {
  render(<Workspace controller={auth} />); await screen.findByRole('heading', { name: 'A fresh start.' })
  fireEvent.click(within(screen.getByRole('navigation', { name: 'Workspace navigation' })).getByRole('button', { name: 'Investments' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Choose an account' }))
  fireEvent.change(await screen.findByLabelText('Saved account'), { target: { value: account.id } }); fireEvent.click(screen.getByRole('button', { name: 'View positions' }))
  fireEvent.click(await screen.findByRole('button', { name: /Saved employee-share instrument/ }))
}
async function openEvidence(kind: 'event' | 'lot' = 'event', history = false) {
  await openDetail()
  fireEvent.click(screen.getByRole('button', { name: kind === 'event' ? 'Inspect account activity' : 'Inspect lot evidence' }))
  await screen.findByRole('heading', { name: kind === 'event' ? 'Account activity' : 'Lot evidence' })
  if (kind === 'lot') { fireEvent.click(screen.getByRole('button', { name: `Inspect observations for lot ${lot.id}` })); await screen.findByRole('button', { name: `Inspect revisions for observation ${id(40)}` }) }
  if (history) { fireEvent.click(screen.getByRole('button', { name: kind === 'event' ? `Inspect revisions for event ${id(30)}` : `Inspect revisions for observation ${id(40)}` })); await screen.findByRole('heading', { name: kind === 'event' ? 'Event revision history' : 'Observation revision history' }) }
  const card = document.querySelectorAll('.wi-evidence')[history && kind === 'lot' ? 1 : 0]!
  fireEvent.click(card.querySelector('summary')!); card.querySelector('details')!.setAttribute('open', '')
}
async function openReceipts(kind: 'event' | 'lot' = 'event', history = false) {
  await openEvidence(kind, history)
  fireEvent.click(screen.getByRole('button', { name: `Inspect batch completion for ${kind === 'event' ? 'event' : 'observation'} ${id(kind === 'event' ? 30 : 40)}, revision ${history ? kind === 'event' ? 3 : 1 : 2}` }))
  await screen.findByRole('heading', { name: 'Batch completion' })
}

async function openScopes() { await openReceipts(); fireEvent.click(screen.getByRole('button', { name: 'Inspect native comparisons' })); await screen.findByRole('heading', { name: 'Native comparisons' }) }
async function openComparison(kind: 'INR cash' | 'USD cash' | 'Position units' = 'INR cash') {
  await openScopes(); fireEvent.click(within(screen.getByRole('article', { name: `${kind} from 2026-05-01 to 2026-05-31` })).getByRole('button', { name: 'Inspect comparison' }))
  await screen.findByRole('heading', { name: `${kind} comparison` })
}
it('preserves native decimal lexemes and independently counted source/combined equations', () => {
  for (const selected of scopes()) {
    expect(nativeScope(selected, id(80))).toEqual(selected)
    expect(nativeComparison(comparison(selected), selected, metadata())).toEqual(comparison(selected))
  }
  expect(scopePage({ items: scopes(), next_after: null }, metadata()).count).toBe(3)
})
it.each([
  { receipt_id: id(90) }, { id: 'invalid' }, { account_id: '00000000-0000-0000-0000-000000000000' }, { currency: 'EUR' }, { currency: null }, { position_id: id(2) },
  { kind: 'equity' }, { date_basis: 'trade' }, { period_start: '0000-01-01' }, { period_start: '2026-02-30' }, { period_end: '2026-04-30' }, { rule_version: true }, { rule_version: 2 }, { input_count: 3 }, { input_count: 1001 }, { input_count: false }, { provider_reference: 'private' },
])('rejects malformed native scope %#', change => expect(() => nativeScope({ ...scope(), ...change }, id(80))).toThrow())
it('keeps cash and unit shape/date-basis rules separate', () => {
  for (const change of [{ currency: 'INR' }, { position_id: null }, { date_basis: 'value' }]) expect(() => nativeScope({ ...scope(102, 'units'), ...change }, id(80))).toThrow()
})
it.each([
  { id: id(99) }, { receipt_id: id(90) }, { account_id: id(90) }, { currency: 'USD' }, { period_start: '2026-05-02' }, { period_end: '2026-06-01' }, { date_basis: 'value' }, { input_count: 10 },
])('binds every immutable comparison scope field %#', change => expect(() => nativeComparison({ ...comparison(), scope: { ...scope(), ...change } }, scope(), metadata())).toThrow())
it('binds unit positions and kind in inspection, without binding every listed scope to the originating account', () => {
  const selected = scope(102, 'units')
  expect(() => nativeComparison({ ...comparison(selected), scope: { ...selected, position_id: id(22) } }, selected, metadata())).toThrow()
  expect(() => nativeComparison(comparison(selected), scope(), metadata())).toThrow()
  expect(scopePage({ items: scopes(), next_after: null }, metadata()).items[1]?.account_id).toBe(id(21))
})
it.each(['1e3', '+1000.00', '01000.00', '1000.000', ' 1000.00', 1000, true, null])('rejects invalid opening precision/type even when its numeric meaning would balance: %s', opening => {
  const value = comparison(); expect(() => nativeComparison({ ...value, source: { ...value.source, opening } }, scope(), metadata())).toThrow()
})
it.each([
  { outcome: 'unbalanced' }, { posted_total: -125.5 }, { posted_total: '-0125.50' }, { posted_total: '-125.500' }, { difference: '0.000' }, { difference: '1.00' }, { calculated_closing: '874.51' }, { posted_total: '-125.51' }, { posted_count: true }, { pending_count: -1 }, { posted_count: 1001 }, { private_reference: 'unexpected' },
])('rejects malformed or inconsistent comparison side %#', change => {
  const value = comparison(); expect(() => nativeComparison({ ...value, source: { ...value.source, ...change } }, scope(), metadata())).toThrow()
})
it('checks high-magnitude financial equations exactly beyond binary floating-point precision', () => {
  const selected = { ...scope(), input_count: 6 }
  const side = { outcome: 'balanced', opening: '999999999999999999.98', posted_total: '0.01', closing: '999999999999999999.99', calculated_closing: '999999999999999999.99', difference: '0', posted_count: 1, pending_count: 0 }
  expect(nativeComparison({ scope: selected, source: side, combined: side }, selected, metadata()).source.opening).toBe(side.opening)
  expect(() => nativeComparison({ scope: selected, source: { ...side, posted_total: '0.02' }, combined: side }, selected, metadata())).toThrow()
})
it.each(['1000000000000000000', '0.0000000000001', '-1'])('rejects out-of-bound or negative unit checkpoints even in a zero-movement equation: %s', opening => {
  const selected = { ...scope(102, 'units'), input_count: 4 }, side = { outcome: 'balanced', opening, closing: opening, calculated_closing: opening, posted_total: '0', difference: '0', posted_count: 0, pending_count: 0 }
  expect(() => nativeComparison({ scope: selected, source: side, combined: side }, selected, metadata())).toThrow()
})
it('validates count identity, source admission and equal native boundaries across both sides', () => {
  const value = comparison()
  expect(() => nativeComparison({ ...value, combined: { ...value.combined, posted_count: 2 } }, scope(), metadata())).toThrow()
  const selected = { ...scope(), input_count: 107 }, overloaded = { ...comparison(selected), source: { ...value.source, posted_count: 100, pending_count: 1 } }
  expect(() => nativeComparison(overloaded, selected, metadata())).toThrow()
  expect(() => nativeComparison({ ...value, combined: { ...value.combined, opening: '2', closing: '2', calculated_closing: '2', posted_total: '0' } }, scope(), metadata())).toThrow()
  expect(() => nativeComparison({ ...value, inputs: [] }, scope(), metadata())).toThrow()
})
function countedComparison(posted: number, pending: number, combinedPosted = 1, combinedPending = 1) {
  const selected = { ...scope(), input_count: 4 + posted + pending + combinedPosted + combinedPending }, value = comparison(selected)
  return { ...value, source: { ...value.source, posted_count: posted, pending_count: pending }, combined: { ...value.combined, posted_count: combinedPosted, pending_count: combinedPending } }
}
it.each([
  { rows: 5, posted: 2, pending: 1, allowed: true }, { rows: 4, posted: 2, pending: 1, allowed: false },
  { rows: 100, posted: 98, pending: 0, allowed: true }, { rows: 100, posted: 99, pending: 0, allowed: false },
  { rows: 100, posted: 49, pending: 49, allowed: true }, { rows: 100, posted: 50, pending: 49, allowed: false },
])('checks source rows plus two distinct checkpoints against receipt rows: $posted posted + $pending pending / $rows rows', ({ rows, posted, pending, allowed }) => {
  const value = countedComparison(posted, pending), receipt = { ...metadata(1), row_count: rows }
  if (allowed) expect(nativeComparison(value, value.scope, receipt)).toEqual(value)
  else expect(() => nativeComparison(value, value.scope, receipt)).toThrow()
})
it('still requires two source checkpoints when opening and closing dates are identical', () => {
  const selected = { ...scope(), period_end: scope().period_start, input_count: 4 }, side = { outcome: 'balanced', opening: '0.00', closing: '0.00', calculated_closing: '0.00', posted_total: '0', difference: '0', posted_count: 0, pending_count: 0 }
  const value = { scope: selected, source: side, combined: side }
  expect(nativeComparison(value, selected, { ...metadata(1), row_count: 2 })).toEqual(value)
  expect(() => nativeComparison(value, selected, { ...metadata(1), row_count: 1 })).toThrow()
})
it('allows combined history to exceed this receipt row count while source rows fit exactly', () => {
  const value = countedComparison(2, 1, 25, 15)
  expect(nativeComparison(value, value.scope, { ...metadata(1), row_count: 5 })).toEqual(value)
})
it('requires the matching reconciled receipt context for equation inspection', () => {
  expect(() => nativeComparison(comparison(), scope(), { ...metadata(), id: id(90) })).toThrow()
  expect(() => nativeComparison(comparison(), scope(), { ...metadata(), mode: 'limited', coverage: 'partial_activity', scope_count: 0 })).toThrow()
})
it('blocks an initial equation response whose source inputs cannot fit its receipt', async () => {
  override('/api/v1/finance/receipts/query', () => ({ items: [{ ...receipt(), row_count: 4, scope_count: 1 }], next_after: null }))
  override('/api/v1/finance/receipts/scopes/query', () => ({ items: [scope()], next_after: null }))
  await openScopes()
  fireEvent.click(screen.getByRole('button', { name: 'Inspect comparison' }))
  await screen.findByRole('heading', { name: 'Unable to verify this response.' })
  expect(auth.snapshot().screen).toMatchObject({ kind: 'blocked', reason: 'protocol' })
  expect(document.querySelector('.wi-comparisons')).toBeNull(); expect(document.body.innerHTML).not.toMatch(/1,000|1000\.00|-125|874\./)
})
it('clears prior and returned values when refreshed source counts exceed their immutable receipt', async () => {
  const initial = countedComparison(2, 1, 17, 1), changed = countedComparison(18, 1)
  changed.source = { ...changed.source, opening: '2000.00', closing: '1874.50', calculated_closing: '1874.50' }
  changed.combined = { ...changed.combined, opening: '2000', closing: '1874.5', calculated_closing: '1874.50' }
  expect(initial.scope).toEqual(changed.scope)
  override('/api/v1/finance/receipts/query', () => ({ items: [{ ...receipt(), scope_count: 1 }], next_after: null }))
  override('/api/v1/finance/receipts/scopes/query', () => ({ items: [initial.scope], next_after: null }))
  override('/api/v1/finance/receipts/scopes/inspect', () => initial)
  await openComparison(); expect(screen.getByText('INR 1,000.00')).toBeTruthy()
  override('/api/v1/finance/receipts/scopes/inspect', () => changed)
  fireEvent.click(screen.getByRole('button', { name: 'Refresh comparison' }))
  await screen.findByRole('heading', { name: 'Unable to verify this response.' })
  expect(auth.snapshot().screen).toMatchObject({ kind: 'blocked', reason: 'protocol' })
  expect(document.querySelector('.wi-comparisons')).toBeNull(); expect(document.body.innerHTML).not.toMatch(/1,000|1000\.00|2,000|2000\.00|-125|874\./)
})
it('validates full traversal counts without keeping prior scope payloads, including maximum 100 scopes', () => {
  let preceding = 0, after: string | null = null
  for (let pageIndex = 0; pageIndex < 4; pageIndex++) {
    const items = Array.from({ length: 25 }, (_, n) => scope(100 + pageIndex * 25 + n)), next_after = pageIndex === 3 ? null : items[24]!.id
    const value = scopePage({ items, next_after }, metadata(100), after, preceding)
    expect(value.items).toHaveLength(25); expect(value.count).toBe((pageIndex + 1) * 25)
    expect(scopePage({ items, next_after }, metadata(100), after, preceding)).toEqual(value)
    after = next_after; preceding = value.count
  }
})
it.each([
  { name: 'early end', count: 26, items: [], next_after: null },
  { name: 'short final', count: 27, items: [scope(125)], next_after: null },
  { name: 'excess final', count: 26, items: Array.from({ length: 25 }, (_, n) => scope(125 + n)), next_after: null },
  { name: 'continuation beyond total', count: 50, items: Array.from({ length: 25 }, (_, n) => scope(125 + n)), next_after: id(149) },
])('rejects $name against immutable scope count', ({ count, items, next_after }) => expect(() => scopePage({ items, next_after }, metadata(count), id(124), 25)).toThrow())
it('rejects limited receipts, unknown page fields, unordered cursors and invalid preceding counts', () => {
  const values = { items: scopes(), next_after: null }
  for (const receipt of [{ ...metadata(), mode: 'limited' as const }, { ...metadata(), scope_count: 0 }, { ...metadata(), scope_count: 101 }]) expect(() => scopePage(values, receipt)).toThrow()
  expect(() => scopePage({ ...values, total: 3 }, metadata())).toThrow()
  expect(() => scopePage({ ...values, items: scopes().reverse() }, metadata())).toThrow()
  expect(() => scopePage(values, metadata(), id(99), 0)).toThrow()
  expect(() => scopePage(values, metadata(), null, 25)).toThrow()
})
it('lists all native scopes with concise labels and expandable technical identities', async () => {
  await openScopes()
  expect(screen.getByRole('heading', { name: 'INR cash' })).toBeTruthy(); expect(screen.getByRole('heading', { name: 'USD cash' })).toBeTruthy(); expect(screen.getByRole('heading', { name: 'Position units' })).toBeTruthy()
  expect(document.querySelectorAll('.wi-comparison-source')).toHaveLength(3)
  expect([...document.querySelectorAll('.wi-comparison-source')].every(element => !element.hasAttribute('open'))).toBe(true)
  expect(screen.queryByText('INR 1,000.00')).toBeNull()
  expect(fetchMock.mock.calls.some(([path]) => String(path).includes('/inputs/'))).toBe(false)
})
it('shows separate source/combined equations, pending counts and original decimal lexemes', async () => {
  await openComparison()
  const source = within(screen.getByRole('article', { name: 'Source report' })), combined = within(screen.getByRole('article', { name: 'Combined saved evidence' }))
  expect(source.getByText('INR 1,000.00')).toBeTruthy(); expect(source.getByText('INR -125.50')).toBeTruthy(); expect(combined.getByText('INR 1,000')).toBeTruthy(); expect(combined.getByText('INR -0.00')).toBeTruthy()
  expect(screen.getByText('Balanced at completion')).toBeTruthy(); expect(screen.getAllByText('Pending entries are excluded from the posted movement.')).toHaveLength(2)
  const calls = fetchMock.mock.calls.filter(([path]) => String(path).includes('/scopes/'))
  expect(calls.map(([path, options]) => [path, JSON.parse(String(options!.body))])).toEqual([['/api/v1/finance/receipts/scopes/query', { receipt_id: id(80), limit: 25, after: null }], ['/api/v1/finance/receipts/scopes/inspect', { id: id(100) }]])
  expect(calls.every(([, options]) => options?.method === 'POST' && options.credentials === 'same-origin' && options.cache === 'no-store' && options.redirect === 'error')).toBe(true)
})
it('preserves exact fractional units without currencies or current-balance claims', async () => {
  await openComparison('Position units')
  const view = document.querySelector('.wi-comparisons')!
  expect(view.textContent).toContain('12.123456789012'); expect(view.textContent).toContain('-0.000000000001'); expect(view.textContent).toContain('12.123456789011')
  expect(view.textContent).not.toMatch(/INR |USD /)
})
it.each(['light', 'dark'])('masks all equation values and accessible content in %s mode', async appearance => {
  theme = appearance; masked = true; const storage = vi.spyOn(Storage.prototype, 'setItem'); await openComparison()
  const view = document.querySelector('.wi-comparisons')!
  expect(view.innerHTML).not.toMatch(/1,000|1000\.00|-125|874\.|0\.00|<progress|<meter/); expect(within(view as HTMLElement).getAllByText('••••').length).toBeGreaterThan(0)
  expect(storage).not.toHaveBeenCalled(); expect(location.hash).toBe('')
  expect((await axe.run(view, { rules: { 'color-contrast': { enabled: false }, region: { enabled: false } } })).violations).toEqual([])
})
it('changes masking and display preference without converting or refetching comparisons', async () => {
  await openComparison(); const reads = fetchMock.mock.calls.filter(([path]) => String(path).includes('/finance/')).length
  fireEvent.change(screen.getByLabelText('Display currency'), { target: { value: 'USD' } }); fireEvent.click(screen.getByRole('button', { name: 'Save preferences' })); await screen.findByText(/USD is your display preference/)
  expect(screen.getByText('INR 1,000.00')).toBeTruthy()
  fireEvent.change(screen.getByLabelText('Amount privacy'), { target: { value: 'hidden' } }); fireEvent.click(screen.getByRole('button', { name: 'Save preferences' })); await screen.findAllByText('••••')
  expect(document.querySelector('.wi-comparisons')?.innerHTML).not.toMatch(/1,000|1000\.00|-125|874\.|0\.00/)
  expect(fetchMock.mock.calls.filter(([path]) => String(path).includes('/finance/'))).toHaveLength(reads)
})
it('does not offer comparison reads for a limited receipt', async () => {
  override('/api/v1/finance/events/query', () => ({ items: [{ ...event, coverage: 'partial_activity' }], next_after: null }))
  override('/api/v1/finance/receipts/query', () => ({ items: [{ ...receipt(), mode: 'limited', coverage: 'partial_activity', scope_count: 0 }], next_after: null }))
  await openReceipts(); expect(screen.queryByRole('button', { name: 'Inspect native comparisons' })).toBeNull(); expect(fetchMock.mock.calls.some(([path]) => String(path).includes('/scopes/'))).toBe(false)
})
it('replaces scope pages and refreshes each page using its preceding count', async () => {
  override('/api/v1/finance/receipts/query', () => ({ items: [{ ...receipt(), scope_count: 26 }], next_after: null }))
  override('/api/v1/finance/receipts/scopes/query', body => body.after ? { items: [scope(125, 'units')], next_after: null } : { items: Array.from({ length: 25 }, (_, n) => scope(100 + n)), next_after: id(124) })
  await openScopes(); fireEvent.click(screen.getByRole('button', { name: 'Refresh comparisons' })); await screen.findByRole('heading', { name: 'Native comparisons' })
  fireEvent.click(screen.getByRole('button', { name: 'Next comparisons' })); await screen.findByRole('heading', { name: 'Position units' })
  expect(screen.queryByRole('heading', { name: 'INR cash' })).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'Refresh comparisons' })); await screen.findByRole('heading', { name: 'Position units' })
  fireEvent.click(screen.getByRole('button', { name: 'First comparisons' })); await screen.findAllByRole('heading', { name: 'INR cash' })
  expect(screen.queryByRole('heading', { name: 'Position units' })).toBeNull()
  expect(fetchMock.mock.calls.filter(([path]) => path === '/api/v1/finance/receipts/scopes/query').map(([, options]) => JSON.parse(String(options!.body)).after)).toEqual([null, null, id(124), id(124), null])
})
it.each(['missing scopes', 'changed scope', 'wrong equation'])('blocks %s and removes preceding values', async failure => {
  if (failure === 'missing scopes') {
    await openReceipts(); override('/api/v1/finance/receipts/scopes/query', () => ({ items: [], next_after: null })); fireEvent.click(screen.getByRole('button', { name: 'Inspect native comparisons' }))
  } else {
    await openComparison(); override('/api/v1/finance/receipts/scopes/inspect', () => failure === 'changed scope' ? { ...comparison(), scope: { ...scope(), account_id: id(90) } } : { ...comparison(), source: { ...comparison().source, difference: '1.00' } })
    fireEvent.click(screen.getByRole('button', { name: 'Refresh comparison' }))
  }
  await screen.findByRole('heading', { name: 'Unable to verify this response.' }); expect(auth.snapshot().screen).toMatchObject({ kind: 'blocked', reason: 'protocol' }); expect(document.body.innerHTML).not.toMatch(/1,000|1000\.00|-125|874\./)
})
it('clears comparison values on unavailable reads without exposing private server errors', async () => {
  await openComparison(); override('/api/v1/finance/receipts/scopes/inspect', () => ({ detail: 'private amount: 123' }), 409)
  fireEvent.click(screen.getByRole('button', { name: 'Refresh comparison' })); await screen.findByRole('alert')
  expect(screen.queryByText('INR 1,000.00')).toBeNull(); expect(screen.queryByText('private amount: 123')).toBeNull(); expect(auth.snapshot().screen.kind).toBe('workspace')
})
it.each(['navigate', 'logout', 'lock'])('discards late comparison responses after %s', async action => {
  await openScopes(); let finish!: (value: Response) => void; const original = fetchMock.getMockImplementation()!
  fetchMock.mockImplementation((path, options) => path === '/api/v1/finance/receipts/scopes/inspect' ? new Promise(resolve => { finish = resolve }) : original(path, options))
  fireEvent.click(within(screen.getByRole('article', { name: 'INR cash from 2026-05-01 to 2026-05-31' })).getByRole('button', { name: 'Inspect comparison' })); await screen.findByText('Checking saved completion evidence…')
  if (action === 'navigate') fireEvent.click(within(screen.getByRole('navigation', { name: 'Workspace navigation' })).getByRole('button', { name: 'Overview' }))
  else if (action === 'logout') fireEvent.click(screen.getByRole('button', { name: 'Sign out here' }))
  else await act(async () => auth.lock())
  await act(async () => finish(response(comparison())))
  expect(document.querySelector('.wi-comparisons')).toBeNull(); expect(screen.queryByText('INR 1,000.00')).toBeNull()
})
it('keeps keyboard focus on comparison headings and supports returning to receipts', async () => {
  await openScopes(); const user = userEvent.setup(), button = within(screen.getByRole('article', { name: 'INR cash from 2026-05-01 to 2026-05-31' })).getByRole('button', { name: 'Inspect comparison' })
  button.focus(); await user.keyboard('{Enter}'); const heading = await screen.findByRole('heading', { name: 'INR cash comparison' }); expect(document.activeElement).toBe(heading)
  fireEvent.click(screen.getByRole('button', { name: 'Back to comparisons' })); expect(document.activeElement).not.toBe(heading); await screen.findByRole('heading', { name: 'Native comparisons' })
  fireEvent.click(screen.getByRole('button', { name: 'Back to receipts' })); await screen.findByRole('heading', { name: 'Receipts for this batch' }); expect(document.querySelector('.wi-comparisons')).toBeNull()
})
