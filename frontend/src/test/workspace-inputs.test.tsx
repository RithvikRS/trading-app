import { act, fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import axe from 'axe-core'
import Workspace from '../../workspace/src/Workspace'
import { AuthController } from '../../workspace/src/auth'
import { receiptContext, savedReceipt } from '../../workspace/src/receipt-evidence'
import { nativeComparison } from '../../workspace/src/comparison-evidence'
import { emptyInputProgress, frozenInput, inputPage } from '../../workspace/src/input-evidence'
import type { InputPart, InputSelection, InputSide } from '../../workspace/src/input-evidence'
import type { NativeComparison, NativeScope } from '../../workspace/src/comparison-evidence'

const id = (n: number) => `74000000-0000-4000-8000-${String(n).padStart(12, '0')}`
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
    if (path === '/api/v1/finance/receipts/inputs/query') { const body = JSON.parse(String(options!.body)), chosen = comparison(scopes().find(item => item.id === body.scope_id)!); return response({ items: inputRows(chosen, body), next_after: null }) }
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
const selectedInput: InputSelection = { side: 'source', part: 'activity' }
const savedComparison = () => nativeComparison(comparison(), scope(), metadata())
function inputRows(value: ReturnType<typeof comparison>, selection: InputSelection) {
  const counts = value[selection.side], count = selection.part === 'activity' ? counts.posted_count + counts.pending_count : 1
  return Array.from({ length: count }, (_, index) => {
    const posted = index < counts.posted_count, reference = id((selection.side === 'source' ? 300 : 600) + (selection.part === 'opening' ? -100 : selection.part === 'closing' ? -99 : index))
    return { id: reference, scope_id: value.scope.id, side: selection.side, part: selection.part, reference_revision: selection.side === 'source' ? 1 : 2, source_row_id: selection.side === 'source' ? reference : null, event_id: selection.side === 'combined' && selection.part === 'activity' ? reference : null, snapshot_id: selection.side === 'combined' && selection.part !== 'activity' ? reference : null,
      source: selection.part === 'activity' ? posted ? index === 0 ? counts.posted_total : value.scope.kind === 'cash' ? '0.00' : '0.000000000000' : value.scope.kind === 'cash' ? '7.00' : '0.000000000009' : counts[selection.part],
      evidence_date: selection.part === 'opening' ? value.scope.period_start : selection.part === 'closing' ? value.scope.period_end : posted ? value.scope.period_start : null,
      posting_state: selection.part === 'activity' ? posted ? 'posted' as const : 'pending' as const : null, kind: value.scope.kind, currency: value.scope.currency }
  })
}
function countsComparison(posted: number, pending: number, side: InputSide = 'combined') {
  const selected = { ...scope(), input_count: 4 + posted + pending }, value = comparison(selected)
  for (const name of ['source', 'combined'] as const) value[name] = { ...value[name], opening: '1000.00', closing: '1000.00', calculated_closing: '1000.00', posted_total: '0.00', difference: '0.00', posted_count: name === side ? posted : 0, pending_count: name === side ? pending : 0 }
  return value
}
function parsed(value = comparison()) { return nativeComparison(value, value.scope, { ...metadata(1), row_count: 100 }) }
const selectionRows = (selection = selectedInput, value = comparison()) => inputRows(value, selection)
async function openInputs(selection: InputSelection = selectedInput, kind: 'INR cash' | 'USD cash' | 'Position units' = 'INR cash') {
  await openComparison(kind); fireEvent.click(screen.getByRole('button', { name: `${selection.side === 'source' ? 'Source report' : 'Combined saved evidence'}: ${selection.part} inputs` })); await screen.findByRole('heading', { name: 'Frozen inputs' })
}

it('retains exact values and all six historical lineage selections in each native scope', () => {
  for (const value of scopes().map(comparison)) for (const side of ['source', 'combined'] as const) for (const part of ['opening', 'activity', 'closing'] as const) {
    const selection = { side, part }, rows = inputRows(value, selection), result = inputPage({ items: rows, next_after: null }, parsed(value), metadata(), context, selection)
    expect(result.items).toEqual(rows); expect(result.progress.count).toBe(rows.length)
  }
})
it.each([
  { id: 'bad' }, { scope_id: id(101) }, { side: 'combined' }, { part: 'opening' }, { reference_revision: 0 }, { reference_revision: true }, { reference_revision: '1' }, { reference_revision: 9007199254740992 },
  { source_row_id: null }, { source_row_id: id(999) }, { event_id: id(999) }, { snapshot_id: id(999) }, { kind: 'units' }, { currency: 'USD' }, { currency: null }, { provider_reference: 'private' },
])('rejects wrong scope, native binding, identity or source lineage %#', change => expect(() => frozenInput({ ...selectionRows()[0], ...change }, savedComparison(), selectedInput, context)).toThrow())
it.each([null, 125.5, true, '1e2', '+1.00', '01.00', ' 1.00', '1.000', '1000000000000000000'])('rejects unsupported cash source spelling/type: %s', source => expect(() => frozenInput({ ...selectionRows()[0], source }, savedComparison(), selectedInput, context)).toThrow())
it('preserves signed zero and twelve-place units, rejecting excess unit precision', () => {
  const value = comparison(scope(102, 'units')), row = inputRows(value, selectedInput)[0]!
  expect(frozenInput({ ...row, source: '-0.000000000000' }, parsed(value), selectedInput, context).source).toBe('-0.000000000000')
  expect(() => frozenInput({ ...row, source: '0.0000000000001' }, parsed(value), selectedInput, context)).toThrow()
})
it.each([
  { date: '2026-05-01', posting: 'posted', valid: true }, { date: '2026-05-31', posting: 'posted', valid: true }, { date: null, posting: 'posted', valid: false },
  { date: null, posting: 'pending', valid: true }, { date: '2026-05-31', posting: 'pending', valid: true }, { date: '2026-06-01', posting: 'pending', valid: false },
  { date: '2026-04-30', posting: 'posted', valid: false }, { date: '2026-02-30', posting: 'posted', valid: false }, { date: '0000-05-01', posting: 'pending', valid: false }, { date: '2026-05-01', posting: null, valid: false },
])('checks original activity dates and posting: $posting / $date', ({ date, posting, valid }) => {
  const row = { ...selectionRows()[0], evidence_date: date, posting_state: posting }
  if (valid) expect(frozenInput(row, savedComparison(), selectedInput, context).evidence_date).toBe(date)
  else expect(() => frozenInput(row, savedComparison(), selectedInput, context)).toThrow()
})
it('requires each checkpoint exact side lexeme, endpoint, null posting and one-row completion', () => {
  for (const side of ['source', 'combined'] as const) for (const part of ['opening', 'closing'] as const) {
    const selection = { side, part }, rows = selectionRows(selection), row = rows[0]!
    for (const change of [{ source: row.source.includes('.') ? row.source.endsWith('0') ? row.source.slice(0, -1) : row.source + '0' : row.source + '.0' }, { evidence_date: null }, { evidence_date: '2026-05-15' }, { posting_state: 'posted' }]) expect(() => frozenInput({ ...row, ...change }, savedComparison(), selection, context)).toThrow()
    for (const items of [[], [row, { ...row, id: id(999), source_row_id: side === 'source' ? id(999) : null, snapshot_id: side === 'combined' ? id(999) : null }]]) expect(() => inputPage({ items, next_after: null }, savedComparison(), metadata(), context, selection)).toThrow()
  }
})
it('keeps combined event and snapshot namespaces distinct from source rows and the origin', () => {
  const activity = { side: 'combined' as const, part: 'activity' as const }, opening = { side: 'combined' as const, part: 'opening' as const }
  const eventRow = selectionRows(activity)[0]!, snapshotRow = selectionRows(opening)[0]!
  for (const change of [{ event_id: null }, { event_id: id(999) }, { source_row_id: id(999) }, { snapshot_id: id(999) }]) expect(() => frozenInput({ ...eventRow, ...change }, savedComparison(), activity, context)).toThrow()
  expect(frozenInput({ ...snapshotRow, id: context.id, snapshot_id: context.id, reference_revision: 45 }, savedComparison(), opening, context).reference_revision).toBe(45)
  expect(() => frozenInput({ ...snapshotRow, snapshot_id: null }, savedComparison(), opening, context)).toThrow()
})
it('binds only an actually occurring origin to its historical source or event revision', () => {
  const row = selectionRows()[0]!, source = { ...row, id: context.source_row_id, source_row_id: context.source_row_id }
  expect(frozenInput(source, savedComparison(), selectedInput, context).reference_revision).toBe(context.source_review_revision)
  expect(() => frozenInput({ ...source, reference_revision: 2 }, savedComparison(), selectedInput, context)).toThrow()
  expect(() => frozenInput(source, savedComparison(), selectedInput, { ...context, kind: 'lot' })).toThrow()
  const opening = { side: 'source' as const, part: 'opening' as const }, checkpoint = selectionRows(opening)[0]!
  expect(() => frozenInput({ ...checkpoint, id: context.source_row_id, source_row_id: context.source_row_id }, savedComparison(), opening, context)).toThrow()
  const selection = { side: 'combined' as const, part: 'activity' as const }, eventRow = { ...selectionRows(selection)[0]!, id: context.id, event_id: context.id }
  expect(frozenInput(eventRow, savedComparison(), selection, context).reference_revision).toBe(2)
  expect(() => frozenInput({ ...eventRow, reference_revision: 3 }, savedComparison(), selection, context)).toThrow()
  expect(frozenInput({ ...row, reference_revision: 53 }, savedComparison(), selectedInput, context).reference_revision).toBe(53)
})
it.each([26, 50, 996])('tracks exact posted/pending completion across %s rows without retaining earlier inputs', count => {
  const selection = { side: 'combined' as const, part: 'activity' as const }, value = countsComparison(Math.floor(count / 2), Math.ceil(count / 2)), rows = inputRows(value, selection)
  let progress = emptyInputProgress, after: string | null = null
  for (let offset = 0; offset < count; offset += 25) {
    const items = rows.slice(offset, offset + 25), next_after = offset + 25 < count ? items[24]!.id : null
    const result = inputPage({ items, next_after }, parsed(value), metadata(), context, selection, after, progress)
    expect(inputPage({ items, next_after }, parsed(value), metadata(), context, selection, after, progress)).toEqual(result)
    expect(Object.keys(result.progress).sort()).toEqual(['count', 'pending', 'posted']); expect(result.items).toHaveLength(items.length)
    progress = result.progress; after = next_after
  }
  expect(progress).toEqual({ count, posted: value.combined.posted_count, pending: value.combined.pending_count })
})
it('allows zero activity but rejects empty checkpoints, false totals and early continuation termination', () => {
  const value = countsComparison(0, 0), zero = parsed(value)
  for (const side of ['source', 'combined'] as const) expect(inputPage({ items: [], next_after: null }, zero, metadata(), context, { side, part: 'activity' }).progress).toEqual(emptyInputProgress)
  expect(() => inputPage({ items: [], next_after: null }, zero, metadata(), context, { side: 'source', part: 'opening' })).toThrow()
  const selection = { side: 'combined' as const, part: 'activity' as const }, many = countsComparison(13, 13), rows = inputRows(many, selection), first = inputPage({ items: rows.slice(0, 25), next_after: rows[24]!.id }, parsed(many), metadata(), context, selection)
  for (const items of [[], [rows[25]!, { ...rows[25]!, id: id(999), event_id: id(999) }]]) expect(() => inputPage({ items, next_after: null }, parsed(many), metadata(), context, selection, first.next_after, first.progress)).toThrow()
  expect(() => inputPage({ items: [rows[25]], next_after: rows[25]!.id }, parsed(many), metadata(), context, selection, first.next_after, first.progress)).toThrow()
  expect(() => inputPage({ items: selectionRows().map(row => ({ ...row, posting_state: 'posted' })), next_after: null }, savedComparison(), metadata(), context, selectedInput)).toThrow()
})
it('rejects duplicate/order/cursor/progress and response-envelope errors', () => {
  const rows = selectionRows(), value = { items: rows, next_after: null }
  for (const broken of [{ ...value, extra: true }, { ...value, items: rows.slice().reverse() }, { ...value, items: [rows[0], rows[0], rows[2]] }, { ...value, next_after: rows[2]!.id }]) expect(() => inputPage(broken, savedComparison(), metadata(), context, selectedInput)).toThrow()
  for (const progress of [{ count: 25, posted: 24, pending: 1 }, { count: 0, posted: 1, pending: 0 }, { count: -1, posted: 0, pending: 0 }]) expect(() => inputPage(value, savedComparison(), metadata(), context, selectedInput, null, progress)).toThrow()
  expect(() => inputPage(value, savedComparison(), metadata(), context, selectedInput, id(299))).toThrow()
})
it('retains source receipt capacity and origin batch/coverage checks without restricting combined history', () => {
  for (const receipt of [{ ...metadata(), id: id(999) }, { ...metadata(), batch_id: id(999) }, { ...metadata(), coverage: 'partial_activity' as const }, { ...metadata(), row_count: 4 }]) expect(() => inputPage({ items: selectionRows(), next_after: null }, savedComparison(), receipt, context, selectedInput)).toThrow()
  const value = countsComparison(99, 0, 'source'); expect(() => inputPage({ items: inputRows(value, selectedInput).slice(0, 25), next_after: id(324) }, value as NativeComparison, { ...metadata(), row_count: 100 }, context, selectedInput)).toThrow()
})
it('shows all six explicit side/part actions and requests only the selected input page', async () => {
  await openComparison()
  for (const side of ['Source report', 'Combined saved evidence']) for (const part of ['opening', 'activity', 'closing']) expect(screen.getByRole('button', { name: `${side}: ${part} inputs` })).toBeTruthy()
  expect(fetchMock.mock.calls.some(([path]) => String(path).includes('/inputs/'))).toBe(false)
  fireEvent.click(screen.getByRole('button', { name: 'Source report: activity inputs' })); const heading = await screen.findByRole('heading', { name: 'Frozen inputs' }); expect(document.activeElement).toBe(heading)
  expect(screen.getByText('INR -125.50')).toBeTruthy(); expect(screen.getByText('INR 0.00')).toBeTruthy(); expect(screen.getByText('Date not supplied')).toBeTruthy()
  expect(screen.getAllByText('Source occurrence')).toHaveLength(3); expect([...document.querySelectorAll('.wi-inputs details')].every(element => !element.hasAttribute('open'))).toBe(true)
  const call = fetchMock.mock.calls.find(([path]) => path === '/api/v1/finance/receipts/inputs/query')!
  expect(JSON.parse(String(call[1]!.body))).toEqual({ scope_id: id(100), side: 'source', part: 'activity', limit: 25, after: null })
  expect(call[1]).toMatchObject({ method: 'POST', credentials: 'same-origin', cache: 'no-store', redirect: 'error' })
})
it('switches all six selections and refetches comparison when returning, with no hidden previous rows', async () => {
  await openInputs()
  for (const side of ['source', 'combined']) {
    fireEvent.change(screen.getByLabelText('Evidence side'), { target: { value: side } }); await screen.findByRole('heading', { name: 'Frozen inputs' })
    for (const part of ['opening', 'closing', 'activity']) {
      fireEvent.change(screen.getByLabelText('Input group'), { target: { value: part } }); await screen.findByRole('heading', { name: 'Frozen inputs' })
      expect(document.querySelectorAll('.wi-inputs .wi-evidence')).toHaveLength(part === 'activity' ? side === 'source' ? 3 : 2 : 1)
    }
  }
  fireEvent.click(screen.getByRole('button', { name: 'Back to comparison' })); await screen.findByRole('heading', { name: 'INR cash comparison' }); expect(document.querySelector('.wi-inputs')).toBeNull()
  expect(fetchMock.mock.calls.filter(([path]) => path === '/api/v1/finance/receipts/scopes/inspect')).toHaveLength(2)
  expect(fetchMock.mock.calls.filter(([path]) => path === '/api/v1/finance/receipts/inputs/query').every(([, options]) => JSON.parse(String(options!.body)).after === null)).toBe(true)
})
it('refreshes later input pages from preceding counters and resets them when switching groups', async () => {
  const value = countsComparison(13, 13), selection = { side: 'combined' as const, part: 'activity' as const }, rows = inputRows(value, selection)
  override('/api/v1/finance/receipts/scopes/query', () => ({ items: [value.scope, scope(101, 'cash', 'USD'), scope(102, 'units')], next_after: null }))
  override('/api/v1/finance/receipts/scopes/inspect', () => value)
  override('/api/v1/finance/receipts/inputs/query', body => body.part !== 'activity' ? { items: inputRows(value, { side: 'combined', part: body.part as InputPart }), next_after: null } : body.after ? { items: rows.slice(25), next_after: null } : { items: rows.slice(0, 25), next_after: rows[24]!.id })
  await openInputs(selection); fireEvent.click(screen.getByRole('button', { name: 'Next input page' })); await screen.findByRole('heading', { name: 'Frozen inputs' }); expect(document.querySelectorAll('.wi-inputs .wi-evidence')).toHaveLength(1)
  fireEvent.click(screen.getByRole('button', { name: 'Refresh inputs' })); await screen.findByRole('heading', { name: 'Frozen inputs' })
  fireEvent.change(screen.getByLabelText('Input group'), { target: { value: 'opening' } }); await screen.findByRole('heading', { name: 'Frozen inputs' })
  fireEvent.change(screen.getByLabelText('Input group'), { target: { value: 'activity' } }); await screen.findByRole('heading', { name: 'Frozen inputs' }); expect(document.querySelectorAll('.wi-inputs .wi-evidence')).toHaveLength(25)
  expect(fetchMock.mock.calls.filter(([path]) => path === '/api/v1/finance/receipts/inputs/query').map(([, options]) => JSON.parse(String(options!.body)).after)).toEqual([null, rows[24]!.id, rows[24]!.id, null, null])
})
it.each(['light', 'dark'])('masks every native input including zero in %s mode without storing values', async appearance => {
  theme = appearance; masked = true; const storage = vi.spyOn(Storage.prototype, 'setItem'); await openInputs()
  const view = document.querySelector('.wi-inputs')!; expect(view.innerHTML).not.toMatch(/125\.50|0\.00|7\.00|<progress|<meter/); expect(screen.getAllByText('••••')).toHaveLength(3); expect(storage).not.toHaveBeenCalled()
  expect((await axe.run(view, { rules: { 'color-contrast': { enabled: false }, region: { enabled: false } } })).violations).toEqual([])
})
it('retains exact units and other-account USD scope through display preference changes without finance refetch', async () => {
  await openInputs(selectedInput, 'USD cash'); expect(screen.getByText('USD -125.50')).toBeTruthy()
  const count = fetchMock.mock.calls.filter(([path]) => String(path).includes('/finance/')).length
  fireEvent.change(screen.getByLabelText('Display currency'), { target: { value: 'USD' } }); fireEvent.click(screen.getByRole('button', { name: 'Save preferences' })); await screen.findByText(/USD is your display preference/)
  expect(screen.getByText('USD -125.50')).toBeTruthy(); expect(fetchMock.mock.calls.filter(([path]) => String(path).includes('/finance/'))).toHaveLength(count)
})
it('preserves twelve-place native units with no inferred cash value', async () => {
  await openInputs(selectedInput, 'Position units'); const view = document.querySelector('.wi-inputs')!
  expect(view.textContent).toContain('-0.000000000001'); expect(view.textContent).toContain('0.000000000000'); expect(view.textContent).not.toMatch(/INR |USD /)
})
it.each(['scope', 'lineage', 'count', 'checkpoint'])('blocks a malformed %s response and clears preceding/returned amounts', async failure => {
  await openInputs(); const selection = failure === 'checkpoint' ? { side: 'source' as const, part: 'opening' as const } : selectedInput
  override('/api/v1/finance/receipts/inputs/query', () => ({ items: failure === 'count' ? [] : selectionRows(selection).map((row, index) => index ? row : { ...row, ...(failure === 'scope' ? { scope_id: id(999) } : failure === 'lineage' ? { source_row_id: id(999) } : { source: '2222.00' }) }), next_after: null }))
  if (failure === 'checkpoint') fireEvent.change(screen.getByLabelText('Input group'), { target: { value: 'opening' } }); else fireEvent.click(screen.getByRole('button', { name: 'Refresh inputs' }))
  await screen.findByRole('heading', { name: 'Unable to verify this response.' }); expect(auth.snapshot().screen).toMatchObject({ kind: 'blocked', reason: 'protocol' }); expect(document.body.innerHTML).not.toMatch(/125\.50|2222\.00|2,222/); expect(document.querySelector('.wi-inputs')).toBeNull()
})
it('clears values and validation context on unavailable input reads, then starts a fresh traversal', async () => {
  await openInputs(); override('/api/v1/finance/receipts/inputs/query', () => ({ detail: 'private financial evidence' }), 409)
  fireEvent.click(screen.getByRole('button', { name: 'Refresh inputs' })); await screen.findByRole('alert'); expect(document.querySelector('.wi-inputs')).toBeNull(); expect(document.body.innerHTML).not.toMatch(/125\.50|private financial evidence/)
  fireEvent.click(screen.getByRole('button', { name: 'Reload batch receipts' })); await screen.findByRole('heading', { name: 'Receipts for this batch' }); expect(document.querySelector('.wi-comparisons')).toBeNull()
})
it.each(['navigate', 'logout', 'lock', 'session'])('discards a late selected-input response after %s', async action => {
  await openInputs(); let finish!: (value: Response) => void; const original = fetchMock.getMockImplementation()!
  fetchMock.mockImplementation((path, options) => path === '/api/v1/finance/receipts/inputs/query' ? new Promise(resolve => { finish = resolve }) : original(path, options))
  fireEvent.change(screen.getByLabelText('Input group'), { target: { value: 'closing' } }); await screen.findByText('Checking saved completion evidence…'); expect(document.querySelector('.wi-inputs')).toBeNull(); expect(screen.queryByText('INR -125.50')).toBeNull()
  if (action === 'navigate') fireEvent.click(within(screen.getByRole('navigation', { name: 'Workspace navigation' })).getByRole('button', { name: 'Overview' }))
  else if (action === 'logout') fireEvent.click(screen.getByRole('button', { name: 'Sign out here' }))
  else if (action === 'session') { const pending = fetchMock.getMockImplementation()!; fetchMock.mockImplementation((path, options) => path === '/api/v1/auth/session' ? Promise.resolve(response({ ...session(), workspace_context: 'e'.repeat(64) })) : pending(path, options)); await act(async () => { auth.suspend(); await auth.bootstrap() }); expect(auth.snapshot().screen).toMatchObject({ kind: 'workspace', session: { workspace_context: 'e'.repeat(64) } }) }
  else await act(async () => auth.lock())
  await act(async () => finish(response({ items: selectionRows({ side: 'source', part: 'closing' }), next_after: null })))
  expect(document.querySelector('.wi-inputs')).toBeNull(); expect(screen.queryByText('INR 874.50')).toBeNull()
})
it('supports keyboard entry and puts focus on the input heading', async () => {
  await openComparison(); const user = userEvent.setup(); screen.getByRole('button', { name: 'Combined saved evidence: closing inputs' }).focus(); await user.keyboard('{Enter}')
  const heading = await screen.findByRole('heading', { name: 'Frozen inputs' }); expect(document.activeElement).toBe(heading)
  expect(screen.getByText('INR 874.5')).toBeTruthy(); fireEvent.click(screen.getByRole('button', { name: 'Back to comparison' })); await screen.findByRole('heading', { name: 'INR cash comparison' })
})

it('shows a permitted zero-activity selection without treating it as an account balance', async () => {
  const value = countsComparison(0, 0)
  override('/api/v1/finance/receipts/scopes/query', () => ({ items: [value.scope, scope(101, 'cash', 'USD'), scope(102, 'units')], next_after: null }))
  override('/api/v1/finance/receipts/scopes/inspect', () => value)
  override('/api/v1/finance/receipts/inputs/query', () => ({ items: [], next_after: null }))
  await openInputs({ side: 'combined', part: 'activity' }); expect(screen.getByText(/No activity inputs were retained for this side/)).toBeTruthy(); expect(document.querySelectorAll('.wi-inputs .wi-evidence')).toHaveLength(0)
  expect((screen.getByRole('button', { name: 'Next input page' }) as HTMLButtonElement).disabled).toBe(true)
})

it('clears displayed input context when an idle session check sees a replacement', async () => {
  await openInputs(); const previous = fetchMock.getMockImplementation()!
  fetchMock.mockImplementation((path, options) => path === '/api/v1/auth/session' ? Promise.resolve(response({ ...session(), workspace_context: 'e'.repeat(64) })) : previous(path, options))
  await act(async () => auth.check()); expect(auth.snapshot().screen).toMatchObject({ kind: 'blocked', reason: 'context' })
  expect(document.querySelector('.wi-inputs')).toBeNull(); expect(document.body.innerHTML).not.toMatch(/125\.50|0\.00|7\.00/)
})
