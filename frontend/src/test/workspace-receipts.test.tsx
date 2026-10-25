import { act, fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import axe from 'axe-core'
import Workspace from '../../workspace/src/Workspace'
import { AuthController } from '../../workspace/src/auth'
import { receipt as snapshotReceipt } from '../../workspace/src/investments'
import { completedRow, completedRows, receiptContext, receiptPage, savedReceipt } from '../../workspace/src/receipt-evidence'

const id = (n: number) => `73000000-0000-4000-8000-${String(n).padStart(12, '0')}`
const position = { id: id(2), account_id: id(1), instrument_id: id(3), holding_form: 'custody', account_state: 'active' }
const lot = { id: id(4), position_id: id(2), account_id: id(1), instrument_id: id(3), account_state: 'active' }
const security = { id: id(3), name: 'Saved employee-share instrument', isin: 'ZZ0000000016', asset_class: 'equity', fund_scheme_id: null, fund_plan: null, fund_option: null, fund_currency: null }
const account = { id: id(1), kind: 'employee_stock', institution: 'ubs', market: 'US', label: 'Employee shares', currencies: ['INR', 'USD'], revision: 1, state: 'active' }
const quantity = { role: 'quantity', source: '12.123456789012', currency: null, missing_reason: null }
const event = { id: id(30), account_id: id(1), position_id: id(2), instrument_id: id(3), kind: 'buy', revision: 2, is_current: true, account_state: 'active', status: 'active', posting_state: 'posted', correction_reason: 'source_correction', trade_date: '2026-05-01', settlement_date: '2026-05-03', booking_date: '2026-05-04', value_date: '2026-05-05', source_row_id: id(10), source_review_revision: 1, source_id: id(11), observation_id: id(12), batch_id: id(13), coverage: 'partial_activity' as const, period_start: '2026-05-01', period_end: '2026-05-31', cash_date_basis: 'settlement', components: [quantity, { role: 'net_cash', source: '-1500.00', currency: 'USD', missing_reason: null }] }
const observation = { ...lot, id: id(40), lot_id: lot.id, revision: 2, is_current: true, scope: 'lot_acquisition', correction_reason: 'source_correction', status: 'active', components: [quantity], as_of_date: '2026-05-31', acquisition_date: '2026-05-01', booking_date: null, source_row_id: id(15), source_review_revision: 2, source_id: id(11), observation_id: id(12), batch_id: id(13), coverage: 'partial_activity' as const, period_start: '2026-05-01', period_end: '2026-05-31', cash_date_basis: null }
const context = receiptContext('event', event)
const receipt = (n = 80, batch = id(13)) => ({ id: id(n), batch_id: batch, batch_revision: 2, mode: 'limited', coverage: 'partial_activity', created_at: '2026-05-31T18:42:10.123456+00:00', row_count: 5, selection_count: 1, scope_count: 0 })
const row = (n = 10) => ({ id: id(n), receipt_id: id(80), review_revision: 1, operation: 'correct', outcome: 'corrected', event_id: id(30), lot_observation_id: null, snapshot_id: null, record_revision: 2, provider_identity_id: null, selection_id: null, selection_revision: null })
const rows = () => [row(), { ...row(14), operation: 'record', outcome: 'linked', event_id: id(31), provider_identity_id: id(71) }, { ...row(15), review_revision: 2, event_id: null, lot_observation_id: id(40) }, { ...row(16), operation: 'record', outcome: 'recorded', event_id: null, snapshot_id: id(50), selection_id: id(72), selection_revision: 3 }, { ...row(17), operation: 'exclude', outcome: 'excluded', event_id: null, record_revision: null }]
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
async function openRows(kind: 'event' | 'lot' = 'event') { await openReceipts(kind); fireEvent.click(screen.getByRole('button', { name: `Inspect row effects for receipt ${id(80)}` })); await screen.findByRole('heading', { name: 'Historical row effects' }) }

it('keeps general historical receipts separate from snapshot mutation receipts', () => {
  for (const coverage of ['snapshot', 'partial_activity', 'unknown'] as const) expect(savedReceipt({ ...receipt(), coverage }, { ...context, coverage }).mode).toBe('limited')
  const reconciled = { ...receipt(), mode: 'reconciled', coverage: 'complete_activity', scope_count: 2 }
  expect(savedReceipt(reconciled, { ...context, coverage: 'complete_activity' }).scope_count).toBe(2)
  expect(() => snapshotReceipt(reconciled)).toThrow(); expect(() => snapshotReceipt(receipt())).toThrow()
  expect(snapshotReceipt({ ...receipt(), coverage: 'snapshot' }).id).toBe(id(80))
})
it.each([
  { batch_id: id(90) }, { batch_revision: 0 }, { batch_revision: true }, { mode: 'complete' }, { mode: 'reconciled' }, { coverage: 'complete_activity' }, { scope_count: 1 },
  { row_count: 0 }, { row_count: 101 }, { selection_count: -1 }, { selection_count: 6 }, { selection_count: 101 }, { scope_count: 101 }, { scope_count: false },
  { created_at: '2026-05-31' }, { created_at: '2026-02-30T12:00:00Z' }, { created_at: '0000-01-01T12:00:00Z' }, { created_at: '2026-05-31T24:00:00Z' }, { created_at: '2026-05-31T12:60:00Z' }, { created_at: '2026-05-31T12:00:60Z' }, { created_at: '2026-05-31T12:00:00-00:00' }, { created_at: '2026-05-31T12:00:00+14:01' }, { created_at: '2026-05-31T12:00:00.1234567Z' }, { private_reference: 'unexpected' }, { baseline: 'unexpected' },
])('rejects malformed receipt metadata %#', changes => expect(() => savedReceipt({ ...receipt(), ...changes }, context)).toThrow())
it.each([
  { receipt_id: id(90) }, { review_revision: false }, { record_revision: 0 }, { operation: 'reopen' }, { outcome: 'pending' }, { operation: 'record', outcome: 'corrected' }, { operation: 'correct', outcome: 'recorded' },
  { event_id: null }, { lot_observation_id: id(40) }, { record_revision: null }, { provider_identity_id: id(71) }, { selection_id: id(72) }, { selection_revision: 1 },
  { operation: 'exclude', outcome: 'excluded' }, { id: id(10), review_revision: 2 }, { id: id(10), event_id: id(31) }, { id: id(10), record_revision: 3 },
  { amount: '1500.00' }, { id: 'invalid' }, { outcome: 'excluded' },
])('rejects inconsistent row effects and originating lineage %#', changes => expect(() => completedRow({ ...row(), ...changes }, id(80), context)).toThrow())
it('accepts exact event and lot lineage while keeping all other batch effects', () => {
  const metadata = savedReceipt(receipt(), context), values = { items: rows(), next_after: null }
  expect(completedRows(values, metadata, context).items).toHaveLength(5)
  expect(completedRows(values, metadata, receiptContext('lot', observation)).items).toHaveLength(5)
  expect(() => completedRow(rows()[2], id(80), receiptContext('event', { ...event, source_row_id: id(15), source_review_revision: 2 }))).toThrow()
  expect(() => completedRow({ ...rows()[4], provider_identity_id: id(71) }, id(80), context)).toThrow()
  expect(() => completedRow({ ...rows()[3], event_id: id(30) }, id(80), context)).toThrow()
})
it('rejects malformed page envelopes, unordered rows, short continuations and count contradictions', () => {
  const metadata = savedReceipt(receipt(), context)
  expect(() => receiptPage({ items: [receipt()], next_after: null, total: 1 }, context)).toThrow()
  expect(() => receiptPage({ items: [receipt(), receipt()], next_after: null }, context)).toThrow()
  expect(() => receiptPage({ items: [receipt()], next_after: id(80) }, context)).toThrow()
  expect(() => receiptPage({ items: [receipt()], next_after: null }, context, id(80))).toThrow()
  for (const values of [{ items: [row()], next_after: null }, { items: [], next_after: null }, { items: rows(), next_after: id(17) }, { items: rows().reverse(), next_after: null }, { items: rows(), next_after: null, total: 5 }]) expect(() => completedRows(values, metadata, context)).toThrow()
  expect(() => completedRows({ items: [], next_after: null }, metadata, context, id(17))).toThrow()
})
it.each(['snapshot', 'unknown', 'complete_activity'] as const)('rejects receipt coverage %s when the originating revision declares partial activity', coverage => {
  const value = { ...receipt(), coverage, ...(coverage === 'complete_activity' ? { mode: 'reconciled', scope_count: 1 } : {}) }
  expect(() => receiptPage({ items: [value], next_after: null }, context)).toThrow()
  expect(receiptPage({ items: [value], next_after: null }, { ...context, coverage }).items).toHaveLength(1)
})
it('requires the exact originating row in a complete single-page result', () => {
  const metadata = savedReceipt(receipt(), context), items = rows().map(item => item.id === id(10) ? { ...item, id: id(9) } : item)
  expect(() => completedRows({ items, next_after: null }, metadata, context)).toThrow()
})
it.each(['first', 'last'] as const)('retains only bounded traversal metadata with the origin on the %s page', origin => {
  const selected = { ...context, source_row_id: id(origin === 'first' ? 100 : 125) }
  const metadata = savedReceipt({ ...receipt(), row_count: 26, selection_count: 0 }, selected)
  const firstValues = { items: Array.from({ length: 25 }, (_, n) => row(100 + n)), next_after: id(124) }
  const first = completedRows(firstValues, metadata, selected)
  expect(first.progress).toEqual({ count: 25, selections: 0, originSeen: origin === 'first' })
  expect(Object.keys(first.progress).sort()).toEqual(['count', 'originSeen', 'selections'])
  const last = completedRows({ items: [row(125)], next_after: null }, metadata, selected, id(124), first.progress)
  expect(last.progress).toEqual({ count: 26, selections: 0, originSeen: true })
  expect(last.items.map(item => item.id)).toEqual([id(125)])
  expect(completedRows({ items: [row(125)], next_after: null }, metadata, selected, id(124), first.progress)).toEqual(last)
  expect(completedRows(firstValues, metadata, selected)).toEqual(first)
})
it.each([
  { name: 'missing origin', count: 26, final: [row(126)], next: null },
  { name: 'excess rows', count: 26, final: Array.from({ length: 25 }, (_, n) => row(125 + n)), next: null },
  { name: 'empty early end', count: 26, final: [], next: null },
  { name: 'short final page', count: 27, final: [row(125)], next: null },
  { name: 'continuation beyond total', count: 50, final: Array.from({ length: 25 }, (_, n) => row(125 + n)), next: id(149) },
])('rejects $name after a valid first page', ({ count, final, next }) => {
  const selected = { ...context, source_row_id: id(125) }, metadata = savedReceipt({ ...receipt(), row_count: count, selection_count: 0 }, selected)
  const first = completedRows({ items: Array.from({ length: 25 }, (_, n) => row(100 + n)), next_after: id(124) }, metadata, selected)
  expect(() => completedRows({ items: final, next_after: next }, metadata, selected, id(124), first.progress)).toThrow()
})
it.each([0, 2])('rejects observed selections that contradict the declared count %s', selection_count => {
  const metadata = savedReceipt({ ...receipt(), selection_count }, context)
  expect(() => completedRows({ items: rows(), next_after: null }, metadata, context)).toThrow()
})
it('tracks selections across pages and verifies their exact final count', () => {
  const selected = { ...context, source_row_id: id(125) }, metadata = savedReceipt({ ...receipt(), row_count: 26, selection_count: 1 }, selected)
  const firstItems = [{ ...rows()[3], id: id(100) }, ...Array.from({ length: 24 }, (_, n) => row(101 + n))]
  const first = completedRows({ items: firstItems, next_after: id(124) }, metadata, selected)
  expect(first.progress).toEqual({ count: 25, selections: 1, originSeen: false })
  expect(completedRows({ items: [row(125)], next_after: null }, metadata, selected, id(124), first.progress).progress).toEqual({ count: 26, selections: 1, originSeen: true })
  const none = completedRows({ items: Array.from({ length: 25 }, (_, n) => row(100 + n)), next_after: id(124) }, metadata, selected)
  expect(() => completedRows({ items: [row(125)], next_after: null }, metadata, selected, id(124), none.progress)).toThrow()
})
it.each(['event', 'lot'] as const)('opens %s completion with exact batch/receipt bindings and whole-batch row effects', async kind => {
  await openRows(kind)
  expect(screen.getByText('Originating evidence revision')).toBeTruthy()
  expect(screen.getAllByText('Another source row in this batch')).toHaveLength(4)
  expect(screen.getByRole('heading', { name: 'Linked existing evidence' })).toBeTruthy()
  expect(screen.getByRole('heading', { name: 'Excluded' })).toBeTruthy()
  expect(screen.getByText(/No financial target was created/)).toBeTruthy()
  expect(screen.getByText('Snapshot '+id(50))).toBeTruthy()
  expect(screen.getByText('Lot observation '+id(40))).toBeTruthy()
  expect(screen.queryByText('USD -1,500.00')).toBeNull(); expect(screen.queryByText('12.123456789012')).toBeNull()
  const calls = fetchMock.mock.calls.filter(([path]) => String(path).includes('/receipts/'))
  expect(calls.map(([path, options]) => [path, JSON.parse(String(options!.body))])).toEqual([['/api/v1/finance/receipts/query', { batch_id: id(13), limit: 25, after: null }], ['/api/v1/finance/receipts/rows/query', { receipt_id: id(80), limit: 25, after: null }]])
  expect(calls.every(([, options]) => options?.method === 'POST' && options.credentials === 'same-origin' && options.cache === 'no-store' && options.redirect === 'error')).toBe(true)
})
it.each(['event', 'lot'] as const)('uses the selected historical %s batch instead of current source metadata', async kind => {
  await openReceipts(kind, true)
  expect(fetchMock.mock.calls.at(-1)?.[1]?.body).toBe(JSON.stringify({ batch_id: id(kind === 'event' ? 113 : 213), limit: 25, after: null }))
  expect(screen.getByText(/Later corrections or changed selections do not rewrite a receipt/)).toBeTruthy()
})
it('shows reconciled receipt scope limitations without fetching or inventing comparisons', async () => {
  override('/api/v1/finance/events/query', () => ({ items: [{ ...event, coverage: 'complete_activity' }], next_after: null }))
  override('/api/v1/finance/receipts/query', () => ({ items: [{ ...receipt(), mode: 'reconciled', coverage: 'complete_activity', scope_count: 2 }], next_after: null }))
  await openReceipts()
  expect(screen.getByText('Reconciled at completion')).toBeTruthy(); expect(screen.getByText(/Equations and compared inputs are not inspected here/)).toBeTruthy()
  expect(fetchMock.mock.calls.some(([path]) => String(path).includes('/scopes/'))).toBe(false)
})
it('paginates receipts without retaining the previous page or assuming time order', async () => {
  override('/api/v1/finance/receipts/query', body => body.after ? { items: [receipt(125)], next_after: null } : { items: Array.from({ length: 25 }, (_, n) => receipt(100 + n)), next_after: id(124) })
  await openReceipts(); fireEvent.click(screen.getByRole('button', { name: 'Next receipt page' }))
  await screen.findByRole('button', { name: `Inspect row effects for receipt ${id(125)}` })
  expect(screen.queryByRole('button', { name: `Inspect row effects for receipt ${id(100)}` })).toBeNull()
  expect(fetchMock.mock.calls.at(-1)?.[1]?.body).toBe(JSON.stringify({ batch_id: id(13), limit: 25, after: id(124) }))
})
it('paginates all batch effects and refreshes each page without retaining or double counting earlier rows', async () => {
  override('/api/v1/finance/events/query', () => ({ items: [{ ...event, source_row_id: id(125) }], next_after: null }))
  override('/api/v1/finance/receipts/query', () => ({ items: [{ ...receipt(), row_count: 26, selection_count: 0 }], next_after: null }))
  override('/api/v1/finance/receipts/rows/query', body => body.after ? { items: [row(125)], next_after: null } : { items: Array.from({ length: 25 }, (_, n) => row(100 + n)), next_after: id(124) })
  await openRows(); expect(screen.queryByText('Originating evidence revision')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'Refresh row effects' })); await screen.findByText(id(100))
  fireEvent.click(screen.getByRole('button', { name: 'Next row page' })); await screen.findByText(id(125))
  expect(screen.queryByText(id(100))).toBeNull(); expect(screen.getByText('Originating evidence revision')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: 'Refresh row effects' })); await screen.findByText(id(125))
  fireEvent.click(screen.getByRole('button', { name: 'First row page' })); await screen.findByText(id(100))
  expect(screen.queryByText(id(125))).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'Next row page' })); await screen.findByText(id(125))
  const cursors = fetchMock.mock.calls.filter(([path]) => path === '/api/v1/finance/receipts/rows/query').map(([, options]) => JSON.parse(String(options!.body)).after)
  expect(cursors).toEqual([null, null, id(124), id(124), null, id(124)])
})
it('keeps absent completion distinct from invalid evidence and supports reload', async () => {
  override('/api/v1/finance/receipts/query', () => ({ items: [], next_after: null })); await openReceipts()
  expect(screen.getByText(/No completion receipt on this page/)).toBeTruthy()
  override('/api/v1/finance/receipts/query', () => ({ items: [receipt()], next_after: null })); fireEvent.click(screen.getByRole('button', { name: 'Refresh receipts' }))
  await screen.findByRole('button', { name: `Inspect row effects for receipt ${id(80)}` })
})
it.each(['light', 'dark'])('keeps preceding values out of the receipt DOM, attributes and storage with masking in %s mode', async appearance => {
  theme = appearance; masked = true; const storage = vi.spyOn(Storage.prototype, 'setItem')
  await openRows(); const reads = fetchMock.mock.calls.filter(([path]) => String(path).includes('/finance/')).length
  fireEvent.change(screen.getByLabelText('Display currency'), { target: { value: 'USD' } }); fireEvent.change(screen.getByLabelText('Amount privacy'), { target: { value: 'visible' } }); fireEvent.click(screen.getByRole('button', { name: 'Save preferences' })); await screen.findByText(/USD is your display preference/)
  expect(document.querySelector('.wi-receipts')?.outerHTML).not.toMatch(/12\.123|1,500|1500\.00|<progress|<meter/)
  expect(fetchMock.mock.calls.filter(([path]) => String(path).includes('/finance/'))).toHaveLength(reads)
  expect(location.hash).toBe(''); expect(storage).not.toHaveBeenCalled()
  expect((await axe.run(document.querySelector('.wi-receipts')!, { rules: { 'color-contrast': { enabled: false }, region: { enabled: false } } })).violations).toEqual([])
})
it('clears prior receipt details on unavailable reads without exposing server text', async () => {
  await openReceipts(); override('/api/v1/finance/receipts/rows/query', () => ({ detail: 'private server detail' }), 409)
  fireEvent.click(screen.getByRole('button', { name: `Inspect row effects for receipt ${id(80)}` })); await screen.findByRole('alert')
  expect(screen.queryByText(receipt().created_at)).toBeNull(); expect(screen.queryByText('private server detail')).toBeNull(); expect(auth.snapshot().screen.kind).toBe('workspace')
})
it.each(['batch', 'receipt', 'lineage'])('fails closed on malformed %s binding and clears completion data', async boundary => {
  await openEvidence()
  if (boundary === 'batch') override('/api/v1/finance/receipts/query', () => ({ items: [receipt(80, id(90))], next_after: null }))
  fireEvent.click(screen.getByRole('button', { name: `Inspect batch completion for event ${id(30)}, revision 2` }))
  if (boundary !== 'batch') {
    await screen.findByRole('heading', { name: 'Batch completion' })
    override('/api/v1/finance/receipts/rows/query', () => ({ items: rows().map((item, index) => index ? item : { ...item, ...(boundary === 'receipt' ? { receipt_id: id(90) } : { record_revision: 3 }) }), next_after: null }))
    fireEvent.click(screen.getByRole('button', { name: `Inspect row effects for receipt ${id(80)}` }))
  }
  await screen.findByRole('heading', { name: 'Unable to verify this response.' }); expect(auth.snapshot().screen).toMatchObject({ kind: 'blocked', reason: 'protocol' })
  expect(screen.queryByRole('heading', { name: 'Batch completion' })).toBeNull(); expect(screen.queryByText('USD -1,500.00')).toBeNull()
})
it.each(['navigate', 'logout', 'lock'])('discards pending row effects after %s', async action => {
  await openReceipts(); let finish!: (value: Response) => void; const original = fetchMock.getMockImplementation()!
  fetchMock.mockImplementation((path, options) => path === '/api/v1/finance/receipts/rows/query' ? new Promise(resolve => { finish = resolve }) : original(path, options))
  fireEvent.click(screen.getByRole('button', { name: `Inspect row effects for receipt ${id(80)}` })); await screen.findByText('Checking saved completion evidence…'); expect(screen.queryByText(receipt().created_at)).toBeNull()
  if (action === 'navigate') fireEvent.click(within(screen.getByRole('navigation', { name: 'Workspace navigation' })).getByRole('button', { name: 'Overview' }))
  else if (action === 'logout') fireEvent.click(screen.getByRole('button', { name: 'Sign out here' }))
  else await act(async () => auth.lock())
  await act(async () => finish(response({ items: rows(), next_after: null })))
  expect(screen.queryByRole('heading', { name: 'Historical row effects' })).toBeNull(); expect(screen.queryByRole('heading', { name: 'Batch completion' })).toBeNull()
})
it('opens a receipt and row effects using the keyboard with stable heading focus', async () => {
  await openEvidence(); const user = userEvent.setup()
  screen.getByRole('button', { name: `Inspect batch completion for event ${id(30)}, revision 2` }).focus(); await user.keyboard('{Enter}')
  const heading = await screen.findByRole('heading', { name: 'Batch completion' }); expect(document.activeElement).toBe(heading)
  await user.tab(); expect(document.activeElement?.textContent).toContain('Refresh receipts')
  screen.getByRole('button', { name: `Inspect row effects for receipt ${id(80)}` }).focus(); await user.keyboard('{Enter}')
  await screen.findByRole('heading', { name: 'Historical row effects' }); expect(document.activeElement).toBe(heading)
})
it('blocks a reconciled receipt attached to partial-activity origin evidence', async () => {
  await openEvidence()
  override('/api/v1/finance/receipts/query', () => ({ items: [{ ...receipt(), coverage: 'complete_activity', mode: 'reconciled', scope_count: 1 }], next_after: null }))
  fireEvent.click(screen.getByRole('button', { name: `Inspect batch completion for event ${id(30)}, revision 2` }))
  await screen.findByRole('heading', { name: 'Unable to verify this response.' })
  expect(auth.snapshot().screen).toMatchObject({ kind: 'blocked', reason: 'protocol' })
  expect(screen.queryByText('Reconciled at completion')).toBeNull(); expect(screen.queryByText('USD -1,500.00')).toBeNull()
})
it('blocks a single-page completion missing its originating row', async () => {
  await openReceipts()
  override('/api/v1/finance/receipts/rows/query', () => ({ items: rows().map(item => item.id === id(10) ? { ...item, id: id(9) } : item), next_after: null }))
  fireEvent.click(screen.getByRole('button', { name: `Inspect row effects for receipt ${id(80)}` }))
  await screen.findByRole('heading', { name: 'Unable to verify this response.' })
  expect(screen.queryByRole('heading', { name: 'Historical row effects' })).toBeNull()
})
it.each([
  { name: 'missing origin', count: 26, selections: 0, final: [row(126)] },
  { name: 'excess rows', count: 26, selections: 0, final: Array.from({ length: 25 }, (_, n) => row(125 + n)) },
  { name: 'early empty end', count: 26, selections: 0, final: [] },
  { name: 'short final page', count: 27, selections: 0, final: [row(125)] },
  { name: 'missing selection', count: 26, selections: 1, final: [row(125)] },
])('blocks $name in a continuation and clears earlier private row details', async ({ count, selections, final }) => {
  override('/api/v1/finance/events/query', () => ({ items: [{ ...event, source_row_id: id(125) }], next_after: null }))
  override('/api/v1/finance/receipts/query', () => ({ items: [{ ...receipt(), row_count: count, selection_count: selections }], next_after: null }))
  override('/api/v1/finance/receipts/rows/query', body => body.after ? { items: final, next_after: null } : { items: Array.from({ length: 25 }, (_, n) => row(100 + n)), next_after: id(124) })
  await openRows(); expect(screen.getByText(id(100))).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: 'Next row page' }))
  await screen.findByRole('heading', { name: 'Unable to verify this response.' })
  expect(auth.snapshot().screen).toMatchObject({ kind: 'blocked', reason: 'protocol' })
  expect(screen.queryByText(id(100))).toBeNull(); expect(screen.queryByRole('heading', { name: 'Batch completion' })).toBeNull()
})
it('restarts traversal after an unavailable continuation without carrying previous counts', async () => {
  override('/api/v1/finance/events/query', () => ({ items: [{ ...event, source_row_id: id(125) }], next_after: null }))
  override('/api/v1/finance/receipts/query', () => ({ items: [{ ...receipt(), row_count: 26, selection_count: 0 }], next_after: null }))
  const first = { items: Array.from({ length: 25 }, (_, n) => row(100 + n)), next_after: id(124) }
  override('/api/v1/finance/receipts/rows/query', () => first)
  await openRows()
  override('/api/v1/finance/receipts/rows/query', () => ({ detail: 'private failure' }), 409)
  fireEvent.click(screen.getByRole('button', { name: 'Next row page' })); await screen.findByRole('alert')
  expect(screen.queryByText(id(100))).toBeNull(); expect(screen.queryByText('private failure')).toBeNull()
  override('/api/v1/finance/receipts/rows/query', body => body.after ? { items: [row(125)], next_after: null } : first)
  fireEvent.click(screen.getByRole('button', { name: 'Reload batch receipts' })); await screen.findByRole('button', { name: `Inspect row effects for receipt ${id(80)}` })
  fireEvent.click(screen.getByRole('button', { name: `Inspect row effects for receipt ${id(80)}` })); await screen.findByText(id(100))
  fireEvent.click(screen.getByRole('button', { name: 'Next row page' })); await screen.findByText('Originating evidence revision')
  expect(auth.snapshot().screen.kind).toBe('workspace')
  const cursors = fetchMock.mock.calls.filter(([path]) => path === '/api/v1/finance/receipts/rows/query').map(([, options]) => JSON.parse(String(options!.body)).after)
  expect(cursors).toEqual([null, id(124), null, id(124)])
})

it('retains the lot history revision guard after returning from completion inspection', async () => {
  await openRows('lot')
  fireEvent.click(screen.getByRole('button', { name: 'Back to lot observations' }))
  await screen.findByRole('button', { name: `Inspect revisions for observation ${id(40)}` })
  expect(screen.getByText('12.123456789012')).toBeTruthy(); expect(document.querySelector('.wi-receipts')).toBeNull()
  override('/api/v1/finance/lots/observations/history', () => ({ items: [{ ...observation, revision: 1, is_current: true, correction_reason: null, components: [{ ...quantity, source: '15.0000' }] }], next_before: null }))
  fireEvent.click(screen.getByRole('button', { name: `Inspect revisions for observation ${id(40)}` }))
  await screen.findByRole('heading', { name: 'Unable to verify this response.' })
  expect(auth.snapshot().screen).toMatchObject({ kind: 'blocked', reason: 'protocol' })
  expect(document.querySelector('.wi-lots')).toBeNull(); expect(document.body.innerHTML).not.toMatch(/12\.123456789012|15\.0000/)
})
