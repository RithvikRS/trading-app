import { act, fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import axe from 'axe-core'
import Workspace from '../../workspace/src/Workspace'
import ReceiptInspection from '../../workspace/src/ReceiptInspection'
import BankSourceRecords from '../../workspace/src/BankSourceRecords'
import { AuthController } from '../../workspace/src/auth'
import { bankAccount } from '../../workspace/src/banking-evidence'
import { eventEvidence, eventIdentity } from '../../workspace/src/activity-evidence'
import { bankProvenance, bankSourcePage, emptySourceProgress, MAX_SOURCE_PAGES } from '../../workspace/src/bank-provenance'
import { receiptPage } from '../../workspace/src/receipt-evidence'
import type { Account } from '../../workspace/src/accounts'

const id = (n: number) => `78000000-0000-4000-8000-${String(n).padStart(12, '0')}`
const hdfc: Account = { id: id(1), kind: 'bank', institution: 'hdfc', market: 'IN', label: 'Everyday account', currencies: ['INR', 'USD'], revision: 1, state: 'active' }
const sbi: Account = { ...hdfc, id: id(2), institution: 'sbi', label: 'Savings account', state: 'archived' }
const cash = (source = '-1500.00', currency = 'INR') => ({ role: 'net_cash', source, currency, missing_reason: null })
const event = () => ({ id: id(30), account_id: id(1), position_id: null, instrument_id: null, kind: 'cash_movement', revision: 2, is_current: true, account_state: 'active', status: 'active', posting_state: 'posted', correction_reason: 'source_correction', trade_date: null, settlement_date: null, booking_date: '2026-05-04', value_date: '2026-05-05', source_row_id: id(10), source_review_revision: 2, source_id: id(11), observation_id: id(12), batch_id: id(13), coverage: 'partial_activity', period_start: '2026-05-01', period_end: '2026-05-31', cash_date_basis: 'value', components: [cash(), { role: 'fee', source: null, currency: 'INR', missing_reason: 'not_supplied' }, { role: 'withholding', source: '0.00000000', currency: 'INR', missing_reason: null }] })
const older = () => ({ ...event(), revision: 1, correction_reason: null, is_current: false, source_row_id: id(6), source_review_revision: 1, source_id: id(4), observation_id: id(5), batch_id: id(3), period_start: '2026-04-01', period_end: '2026-04-30', booking_date: '2026-04-04', value_date: '2026-04-05', components: [cash('100.00')] })
const newer = () => ({ ...event(), revision: 3, source_row_id: id(110), source_review_revision: 4, source_id: id(111), observation_id: id(112), batch_id: id(113), coverage: 'snapshot', period_start: '2026-09-01', period_end: '2026-09-30', booking_date: '2026-09-04', value_date: null, cash_date_basis: 'booking', components: [cash('2150.50', 'USD')] })
const parsed = () => eventEvidence(event(), hdfc.id)
const context = () => bankProvenance(bankAccount(hdfc), parsed())
type FixtureOrigin = Pick<ReturnType<typeof event>, 'id' | 'revision' | 'source_row_id' | 'source_review_revision' | 'source_id' | 'observation_id' | 'batch_id' | 'coverage' | 'period_start' | 'period_end'>
const observation = (origin: FixtureOrigin = event(), n = origin.observation_id) => ({ id: n, source_id: origin.source_id, previous_id: null, is_current: false, coverage: origin.coverage, period_start: origin.period_start, period_end: origin.period_end })
const sources = (origin: FixtureOrigin = event()) => [observation(origin), { ...observation(origin, id(500)), previous_id: origin.observation_id, is_current: true, coverage: 'complete_activity', period_start: '2026-10-01', period_end: '2026-10-31' }]
const receipt = (origin: FixtureOrigin = event()) => ({ id: id(origin.revision * 1000), batch_id: origin.batch_id, batch_revision: 1, mode: origin.coverage === 'complete_activity' ? 'reconciled' : 'limited', coverage: origin.coverage, created_at: '2026-10-24T10:11:12Z', row_count: 5, selection_count: 1, scope_count: origin.coverage === 'complete_activity' ? 2 : 0 })
const effect = (n: number, origin: FixtureOrigin = event()) => ({ id: id(n), receipt_id: receipt(origin).id, review_revision: 1, operation: 'record', outcome: 'recorded', event_id: id(900), lot_observation_id: null, snapshot_id: null, record_revision: 1, provider_identity_id: null, selection_id: null, selection_revision: null })
const effects = (origin: FixtureOrigin = event()) => [
  { ...effect(1, origin), id: origin.source_row_id, review_revision: origin.source_review_revision, operation: origin.revision === 1 ? 'record' : 'correct', outcome: origin.revision === 1 ? 'recorded' : 'corrected', event_id: origin.id, record_revision: origin.revision },
  { ...effect(600, origin), outcome: 'linked', provider_identity_id: id(901) },
  { ...effect(601, origin), event_id: null, snapshot_id: id(902), selection_id: id(903), selection_revision: 1 },
  { ...effect(602, origin), operation: 'exclude', outcome: 'excluded', event_id: null, record_revision: null },
  { ...effect(603, origin), event_id: null, lot_observation_id: id(904) },
]
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
    if (path === '/api/v1/finance/accounts/query') return response({ items: [hdfc, sbi], next_after: null })
    const body = JSON.parse(String(options?.body ?? '{}'))
    if (path === '/api/v1/finance/events/query') return response({ items: [{ ...event(), account_id: body.account_id, account_state: body.account_id === sbi.id ? 'archived' : 'active' }], next_after: null })
    if (path === '/api/v1/finance/events/history') return response({ items: [newer(), { ...event(), is_current: false }, older()], next_before: null })
    const origins = [older(), event(), newer()], origin = origins.find(item => path === '/api/v1/finance/imports/observations/query' ? item.source_id === body.source_id : path === '/api/v1/finance/receipts/query' ? item.batch_id === body.batch_id : receipt(item).id === body.receipt_id) ?? event()
    if (path === '/api/v1/finance/imports/observations/query') return response({ items: sources(origin), next_after: null })
    if (path === '/api/v1/finance/receipts/query') return response({ items: [receipt(origin)], next_after: null })
    if (path === '/api/v1/finance/receipts/rows/query') return response({ items: effects(origin), next_after: null })
    return response({}, 404)
  })
})
afterEach(() => { auth.lock(); vi.unstubAllGlobals(); document.cookie = 'trading_dev_csrf=; Max-Age=0; Path=/'; delete document.documentElement.dataset.theme })
function override(path: string, handler: (body: Record<string, unknown>) => unknown, status = 200) { const previous = fetchMock.getMockImplementation()!; fetchMock.mockImplementation((url, options) => url === path ? Promise.resolve(response(handler(JSON.parse(String(options!.body))), status)) : previous(url, options)) }
async function openActivity(account = 'HDFC Everyday account') {
  render(<Workspace controller={auth} />); await screen.findByRole('heading', { name: 'A fresh start.' })
  fireEvent.click(within(screen.getByRole('navigation', { name: 'Workspace navigation' })).getByRole('button', { name: 'Banking' })); await screen.findByRole('button', { name: `View saved activity for ${account}` })
  fireEvent.click(screen.getByRole('button', { name: `View saved activity for ${account}` })); await screen.findByRole('heading', { name: 'Saved account activity' })
}
async function action(label: 'Source records' | 'Batch receipts', revision = 2) {
  const button = screen.getByLabelText(`${label} for event ${id(30)}, revision ${revision}`)
  const details = button.closest('details')!; if (!details.open) fireEvent.click(within(details).getByText('Source details'))
  fireEvent.click(button); await screen.findByRole('heading', { name: label === 'Source records' ? 'Source records' : 'Batch completion' })
}
async function openRows() { await action('Batch receipts'); fireEvent.click(screen.getByRole('button', { name: `Row effects for receipt ${receipt().id}` })); await screen.findByRole('heading', { name: 'Historical row effects' }) }
const calls = () => fetchMock.mock.calls.filter(([path]) => String(path).includes('/finance/'))

it('keeps immutable origin metadata without financial components and preserves the stronger return floor', () => {
  const current = context(); expect(current.origin).not.toHaveProperty('components'); expect(current.origin).not.toHaveProperty('booking_date'); expect(current.back).toEqual({ kind: 'activity' })
  const root = eventIdentity(parsed()), old = bankProvenance(bankAccount(hdfc), eventEvidence(older(), hdfc.id), root), fresh = bankProvenance(bankAccount(hdfc), eventEvidence(newer(), hdfc.id), root)
  expect(old.origin.revision).toBe(1); expect(old.origin.batch_id).toBe(id(3)); expect(old.back).toMatchObject({ root: { revision: 2 }, highestSeenRevision: 2 }); expect(fresh.back).toMatchObject({ root: { revision: 2 }, highestSeenRevision: 3 })
})
it.each([{ id: id(999) }, { account_id: sbi.id }, { position_id: id(999) }, { instrument_id: id(999) }, { kind: 'fee' }, { revision: 0 }, { revision: 1.5 }])('rejects inconsistent historical return identity %#', change => expect(() => bankProvenance(bankAccount(hdfc), parsed(), { ...eventIdentity(parsed()), ...change } as ReturnType<typeof eventIdentity>)).toThrow())
it.each([{ account_id: sbi.id }, { position_id: id(5), instrument_id: id(6) }, { components: [cash('1.00','EUR')] }])('rejects inconsistent bank origin %#', change => expect(() => bankProvenance(bankAccount(hdfc), { ...parsed(), ...change } as ReturnType<typeof parsed>)).toThrow())
it('allows changed other-source observations and a replaced origin while binding its immutable coverage and dates', () => {
  const result = bankSourcePage({ items: sources(), next_after: null }, context().origin); expect(result.items[0]!.is_current).toBe(false); expect(result.items[1]!.coverage).toBe('complete_activity'); expect(result.progress).toEqual({ pages: 1, originSeen: true })
  expect(bankSourcePage({ items: [{ ...observation(), is_current: true }], next_after: null }, context().origin).items[0]!.is_current).toBe(true)
})
it.each([{ source_id: id(999) }, { coverage: 'complete_activity' }, { period_start: '2026-04-01' }, { period_end: '2026-06-01' }, { period_start: '2026-02-30' }, { previous_id: id(12) }, { extra: 'private' }])('rejects source mismatch and changed or malformed origin %#', change => expect(() => bankSourcePage({ items: [{ ...observation(), ...change }], next_after: null }, context().origin)).toThrow())
it('requires the known observation only when traversal ends and retains only progress metadata', () => {
  const origin = { ...context().origin, observation_id: id(125) }, first = Array.from({ length: 25 }, (_, n) => observation(event(), id(100+n)))
  const page = bankSourcePage({ items: first, next_after: id(124) }, origin); expect(page.progress).toEqual({ pages: 1, originSeen: false }); expect(Object.keys(page.progress)).toEqual(['pages','originSeen'])
  const final = { items: [observation(event(), id(125))], next_after: null }; expect(bankSourcePage(final, origin, id(124), page.progress).progress).toEqual({ pages: 2, originSeen: true })
  expect(bankSourcePage(final, origin, id(124), page.progress).progress.pages).toBe(2)
  expect(() => bankSourcePage({ items: [observation(event(), id(126))], next_after: null }, origin, id(124), page.progress)).toThrow()
  expect(() => bankSourcePage({ items: [], next_after: null }, origin)).toThrow()
  expect(() => bankSourcePage({ items: [observation(event(), id(126))], next_after: null }, origin)).toThrow()
})
it.each([{ pages: -1, originSeen: false }, { pages: 100, originSeen: true }, { pages: 0, originSeen: true }, { pages: 0.5, originSeen: false }, { pages: 0, originSeen: 'yes' }])('rejects invalid source traversal metadata %#', progress => expect(() => bankSourcePage({ items: sources(), next_after: null }, context().origin, null, progress as typeof emptySourceProgress)).toThrow())
it('rejects malformed source pagination and retains an explicit cap without claiming complete traversal', () => {
  expect(() => bankSourcePage({ items: sources(), next_after: id(500) }, context().origin)).toThrow()
  expect(() => bankSourcePage({ items: [observation(), observation()], next_after: null }, context().origin)).toThrow()
  const origin = { ...context().origin, observation_id: id(999) }, items = Array.from({ length: 25 }, (_, n) => observation(event(), id(100+n)))
  const page = bankSourcePage({ items, next_after: id(124) }, origin, id(99), { pages: 99, originSeen: false }); expect(page.progress.pages).toBe(MAX_SOURCE_PAGES)
  const onPage = vi.fn(); render(<BankSourceRecords context={{ ...context(), origin }} page={page} after={id(99)} preceding={{ pages: 99, originSeen: false }} disabled={false} onPage={onPage} onBack={() => {}} />)
  expect((screen.getByRole('button', { name: 'Next source page' }) as HTMLButtonElement).disabled).toBe(true); expect(screen.getByText(/Some source records are not displayed/)).toBeTruthy(); expect(onPage).not.toHaveBeenCalled()
})
it('opens source-wide records without retaining amounts and refetches the account on return', async () => {
  await openActivity(); await action('Source records'); expect(screen.getByText('Source-wide records, including other accounts and periods.')).toBeTruthy(); expect(screen.getByText('Source for the opened revision')).toBeTruthy(); expect(screen.getByText('Source claims complete activity')).toBeTruthy(); expect(document.querySelector('.wb-workspace')!.innerHTML).not.toMatch(/1,500|1500\.00|0\.00000000/)
  expect(JSON.parse(String(calls().at(-1)![1]!.body))).toEqual({ source_id: id(11), limit: 25, after: null })
  fireEvent.click(screen.getByRole('button', { name: 'Back to saved activity' })); await screen.findByText('INR -1,500.00'); expect(calls().at(-1)![0]).toBe('/api/v1/finance/events/query')
})
it('preserves source page refresh progress and resets on first page', async () => {
  override('/api/v1/finance/events/query', () => ({ items: [{ ...event(), observation_id: id(125) }], next_after: null }))
  override('/api/v1/finance/imports/observations/query', body => body.after ? { items: [observation(event(), id(125))], next_after: null } : { items: Array.from({ length: 25 }, (_, n) => observation(event(), id(100+n))), next_after: id(124) })
  await openActivity(); await action('Source records'); expect(screen.queryByText('Source for the opened revision')).toBeNull(); fireEvent.click(screen.getByRole('button', { name: 'Next source page' })); await screen.findByText('Source page 2'); fireEvent.click(screen.getByRole('button', { name: 'Refresh source records' })); await screen.findByText('Source page 2'); expect(document.querySelectorAll('.wb-source-records .wb-event')).toHaveLength(1)
  fireEvent.click(screen.getByRole('button', { name: 'First source page' })); await screen.findByText('Source page 1'); expect(calls().filter(([path]) => String(path).endsWith('observations/query')).map(([, options]) => JSON.parse(String(options!.body)).after)).toEqual([null,id(124),id(124),null])
})
it.each(['source', 'receipt'])('opens a historical %s using its original source and returns with the stronger known floor', async kind => {
  await openActivity(); fireEvent.click(screen.getByRole('button', { name: `Revision history for event ${id(30)}` })); await screen.findByRole('heading', { name: 'Event revision history' }); await action(kind === 'source' ? 'Source records' : 'Batch receipts',1)
  expect(JSON.parse(String(calls().at(-1)![1]!.body))).toMatchObject(kind === 'source' ? { source_id: id(4) } : { batch_id: id(3) })
  override('/api/v1/finance/events/history', () => ({ items: [{ ...older(), is_current: true }], next_before: null })); fireEvent.click(screen.getByRole('button', { name: 'Back to revision history' })); await screen.findByRole('heading', { name: 'Unable to verify this response.' }); expect(document.querySelector('.wb-workspace')).toBeNull(); expect(document.body.innerHTML).not.toMatch(/1500|1,500|100\.00/)
})
it('retains a newer clicked revision floor after receipt navigation', async () => {
  await openActivity(); fireEvent.click(screen.getByRole('button', { name: `Revision history for event ${id(30)}` })); await screen.findByRole('heading', { name: 'Event revision history' }); await action('Batch receipts',3)
  override('/api/v1/finance/events/history', () => ({ items: [event()], next_before: null })); fireEvent.click(screen.getByRole('button', { name: 'Back to revision history' })); await screen.findByRole('heading', { name: 'Unable to verify this response.' })
})
it('shows whole-batch effects including nonbank targets without exposing bank comparisons', async () => {
  await openActivity(); await openRows(); expect(screen.getByRole('heading',{name:'Import details'})).toBeTruthy(); expect(screen.getByText('Whole-batch records, including other accounts and positions.')).toBeTruthy(); expect(screen.getByText('Originating revision')).toBeTruthy(); expect(screen.getAllByText('Another batch row')).toHaveLength(4); expect(screen.getByText('Linked existing evidence')).toBeTruthy(); expect(screen.getByText('Excluded')).toBeTruthy(); expect(screen.getByText('Lot observation '+id(904))).toBeTruthy()
  expect(document.querySelector('.wb-workspace')!.innerHTML).not.toMatch(/1,500|1500\.00|0\.00000000/); expect(screen.queryByRole('button',{name:'Inspect native comparisons'})).toBeNull()
})
it('keeps true complete-activity metadata with explicit comparison entry and no automatic reads', async () => {
  const complete = { ...event(), coverage: 'complete_activity' }; override('/api/v1/finance/events/query', () => ({ items: [complete], next_after: null })); override('/api/v1/finance/receipts/query', () => ({ items: [receipt(complete)], next_after: null }))
  await openActivity(); await action('Batch receipts'); expect(screen.getByText('Reconciled at completion')).toBeTruthy(); expect(screen.getByRole('button',{name:'Saved comparisons'})).toBeTruthy(); expect(screen.queryByRole('button',{name:'Inspect native comparisons'})).toBeNull(); expect(document.querySelector('.wi-receipts')!.innerHTML).not.toMatch(/Inspect native comparisons|Original input rows are available/)
  expect(calls().every(([path]) => !String(path).includes('/receipts/scopes/') && !String(path).includes('/receipts/inputs/'))).toBe(true)
})
it('allows empty receipt evidence without treating it as a zero balance', async () => {
  override('/api/v1/finance/receipts/query', () => ({ items: [], next_after: null })); await openActivity(); await action('Batch receipts'); expect(screen.getByText(/No completion receipt on this page/)).toBeTruthy(); expect((screen.getByRole('button',{name:'Next receipt page'}) as HTMLButtonElement).disabled).toBe(true)
})
it.each(['source', 'receipt', 'rows', 'rows refresh'])('drops account and origin context on unavailable %s and retries from the directory', async failure => {
  await openActivity()
  if (failure === 'source') { await action('Source records'); override('/api/v1/finance/imports/observations/query', () => ({ detail:'private' }),409); fireEvent.click(screen.getByRole('button',{name:'Refresh source records'})) }
  else { await action('Batch receipts'); if (failure.startsWith('rows')) { if (failure === 'rows refresh') { fireEvent.click(screen.getByRole('button',{name:`Row effects for receipt ${receipt().id}`})); await screen.findByRole('heading',{name:'Historical row effects'}) } override('/api/v1/finance/receipts/rows/query', () => ({ detail:'private' }),409); fireEvent.click(screen.getByRole('button',{name: failure === 'rows' ? `Row effects for receipt ${receipt().id}` : 'Refresh row effects'})) } else { override('/api/v1/finance/receipts/query', () => ({ detail:'private' }),409); fireEvent.click(screen.getByRole('button',{name:'Refresh receipts'})) } }
  await screen.findByRole('alert'); expect(screen.queryByText('HDFC · Everyday account')).toBeNull(); expect(screen.queryByRole('button',{name:'Reload batch receipts'})).toBeNull(); expect(document.querySelector('.wi-receipts')).toBeNull(); expect(document.querySelector('.wb-workspace')!.innerHTML).not.toMatch(/78000000|1,500|1500\.00/)
  fireEvent.click(screen.getByRole('button',{name:'Reload saved bank accounts'})); await screen.findByRole('button',{name:'View saved activity for HDFC Everyday account'}); expect(calls().at(-1)![0]).toBe('/api/v1/finance/accounts/query')
})
it.each(['source identity','origin period','origin missing','receipt coverage','receipt batch','origin revision','row count'])('blocks inconsistent %s and clears prior data', async failure => {
  await openActivity()
  if (failure.startsWith('source') || failure.startsWith('origin p') || failure === 'origin missing') { override('/api/v1/finance/imports/observations/query', () => ({ items:[{...observation(),...(failure === 'source identity' ? {source_id:id(999)} : failure === 'origin period' ? {period_start:'2026-04-01'} : {id:id(999)})}],next_after:null })); await act(async () => { const b=screen.getByLabelText(`Source records for event ${id(30)}, revision 2`); fireEvent.click(b) }) }
  else if (failure.startsWith('receipt')) { override('/api/v1/finance/receipts/query', () => ({items:[{...receipt(),...(failure === 'receipt coverage' ? {coverage:'snapshot'} : {batch_id:id(999)})}],next_after:null})); fireEvent.click(screen.getByLabelText(`Batch receipts for event ${id(30)}, revision 2`)) }
  else { await action('Batch receipts'); override('/api/v1/finance/receipts/rows/query', () => ({items:failure === 'row count' ? effects().slice(0,4) : effects().map((row,index) => index ? row : {...row,record_revision:1}),next_after:null})); fireEvent.click(screen.getByRole('button',{name:`Row effects for receipt ${receipt().id}`})) }
  await screen.findByRole('heading',{name:'Unable to verify this response.'}); expect(document.querySelector('.wb-workspace')).toBeNull(); expect(document.body.innerHTML).not.toMatch(/1,500|1500\.00|2026-05/)
})
it.each(['navigate','logout','lock','session'])('discards a late nested bank receipt response after %s', async actionName => {
  await openActivity(); await action('Batch receipts'); let finish!: (r:Response)=>void; const prior=fetchMock.getMockImplementation()!
  fetchMock.mockImplementation((path,options)=>path === '/api/v1/finance/receipts/rows/query' ? new Promise(resolve=>{finish=resolve}) : prior(path,options)); fireEvent.click(screen.getByRole('button',{name:`Row effects for receipt ${receipt().id}`})); await screen.findByText('Checking saved completion evidence…')
  if(actionName==='navigate')fireEvent.click(within(screen.getByRole('navigation',{name:'Workspace navigation'})).getByRole('button',{name:'Overview'}))
  else if(actionName==='logout')fireEvent.click(screen.getByRole('button',{name:'Sign out here'}))
  else if(actionName==='session'){const old=fetchMock.getMockImplementation()!;fetchMock.mockImplementation((path,options)=>path==='/api/v1/auth/session'?Promise.resolve(response({...session(),workspace_context:'e'.repeat(64)})):old(path,options));await act(async()=>{auth.suspend();await auth.bootstrap()})}
  else await act(async()=>auth.lock())
  await act(async()=>finish(response({items:effects(),next_after:null})));expect(document.querySelector('.wb-workspace')).toBeNull();expect(document.body.innerHTML).not.toMatch(/78000000|1,500/)
})
it.each(['light','dark'])('preserves keyboard, privacy and accessible structure for %s provenance', async mode => {
  theme=mode;masked=true;await openActivity();expect(screen.getAllByText('••••')).toHaveLength(3);const user=userEvent.setup();const detail=screen.getByText('Source details');await user.click(detail);screen.getByRole('button',{name:`Source records for event ${id(30)}, revision 2`}).focus();await user.keyboard('{Enter}');expect(document.activeElement).toBe(await screen.findByRole('heading',{name:'Source records'}))
  expect((await axe.run(document.querySelector('.wb-workspace')!,{rules:{'color-contrast':{enabled:false},region:{enabled:false}}})).violations).toEqual([])
  fireEvent.click(screen.getByRole('button',{name:'Back to saved activity'}));await screen.findByRole('heading',{name:'Saved account activity'});await openRows();expect(document.querySelector('.wb-workspace')!.innerHTML).not.toMatch(/1,500|1500\.00|0\.00000000/)
  expect((await axe.run(document.querySelector('.wb-workspace')!,{rules:{'color-contrast':{enabled:false},region:{enabled:false}}})).violations).toEqual([])
})
it('keeps archived account context and native preferences without provenance refetch', async()=>{
  await openActivity('SBI Savings account');await action('Source records');expect(screen.getByText('SBI · Savings account')).toBeTruthy();const before=calls().length
  fireEvent.change(screen.getByLabelText('Display currency'),{target:{value:'USD'}});fireEvent.click(screen.getByRole('button',{name:'Save preferences'}));await screen.findByText('Saved to your account');expect(calls()).toHaveLength(before)
})
it('preserves full-mode receipt comparison copy and local unavailable retry', async()=>{
  const complete={...event(),coverage:'complete_activity'},ctx=bankProvenance(bankAccount(hdfc),eventEvidence(complete,hdfc.id)).origin
  await auth.bootstrap();render(<section><h2>Saved evidence</h2><ReceiptInspection auth={auth} context={ctx} initial={receiptPage({items:[receipt(complete)],next_after:null},ctx)} masked={false} busy={false} navigation={{mode:'full'}} onBack={()=>{}} /></section>)
  expect(screen.getByRole('button',{name:'Inspect native comparisons'})).toBeTruthy();expect(screen.getByText(/Original input rows are available/)).toBeTruthy();override('/api/v1/finance/receipts/query',()=>({detail:'private'}),409);fireEvent.click(screen.getByRole('button',{name:'Refresh receipts'}));await screen.findByRole('alert');expect(screen.getByRole('button',{name:'Reload batch receipts'})).toBeTruthy();expect(document.querySelector('.wi-receipts')).not.toBeNull()
})
it('uses only existing fixed POST reads with bounded bodies and no private browser storage',async()=>{
  const storage=vi.spyOn(Storage.prototype,'setItem');await openActivity();await action('Source records');fireEvent.click(screen.getByRole('button',{name:'Back to saved activity'}));await screen.findByRole('heading',{name:'Saved account activity'});await openRows()
  const allowed=['/accounts/query','/events/query','/events/history','/imports/observations/query','/receipts/query','/receipts/rows/query'];for(const [path,options]of calls()){expect(allowed.some(route=>String(path)==='/api/v1/finance'+route)).toBe(true);expect(options).toMatchObject({method:'POST',credentials:'same-origin',cache:'no-store',redirect:'error'});expect(JSON.parse(String(options!.body)).limit).toBe(25)}expect(storage).not.toHaveBeenCalled();storage.mockRestore()
})

it.each(['pending','cancelled'])('opens source evidence for a %s record without changing its meaning',async state=>{
  override('/api/v1/finance/events/query',()=>({items:[{...event(),...(state==='pending'?{posting_state:'pending',value_date:null}:{status:'cancelled',correction_reason:'cancellation',components:[]})}],next_after:null}))
  await openActivity();expect(screen.getByText(state==='pending'?'Pending evidence is not a posted movement.':'Cancelled record. This revision has no amounts; earlier amounts remain in history.')).toBeTruthy();await action('Source records');expect(screen.getByText('Source for the opened revision')).toBeTruthy()
})
it('returns from older source evidence to valid newer revision history',async()=>{
  await openActivity();fireEvent.click(screen.getByRole('button',{name:`Revision history for event ${id(30)}`}));await screen.findByRole('heading',{name:'Event revision history'});await action('Source records',1);fireEvent.click(screen.getByRole('button',{name:'Back to revision history'}));await screen.findByText('USD 2,150.50');expect(screen.getByText('INR 100.00')).toBeTruthy();expect(calls().at(-1)![0]).toBe('/api/v1/finance/events/history')
})
it('preserves unknown source coverage with exact absent period fields',()=>{
  const origin={...context().origin,coverage:'unknown' as const,period_start:null,period_end:null};const record={...observation(),coverage:'unknown',period_start:null,period_end:null}
  expect(bankSourcePage({items:[record],next_after:null},origin).items[0]!.period_start).toBeNull();expect(()=>bankSourcePage({items:[{...record,period_start:'2026-05-01',period_end:'2026-05-31'}],next_after:null},origin)).toThrow()
})
it.each(['navigate','logout','lock','session'])('discards a late bank source response after %s',async actionName=>{
  await openActivity();let finish!:(r:Response)=>void;const prior=fetchMock.getMockImplementation()!;fetchMock.mockImplementation((path,options)=>path==='/api/v1/finance/imports/observations/query'?new Promise(resolve=>{finish=resolve}):prior(path,options));fireEvent.click(screen.getByLabelText(`Source records for event ${id(30)}, revision 2`));await screen.findByText('Checking saved bank evidence…');expect(screen.queryByText('HDFC · Everyday account')).toBeNull()
  if(actionName==='navigate')fireEvent.click(within(screen.getByRole('navigation',{name:'Workspace navigation'})).getByRole('button',{name:'Overview'}))
  else if(actionName==='logout')fireEvent.click(screen.getByRole('button',{name:'Sign out here'}))
  else if(actionName==='session'){const old=fetchMock.getMockImplementation()!;fetchMock.mockImplementation((path,options)=>path==='/api/v1/auth/session'?Promise.resolve(response({...session(),workspace_context:'e'.repeat(64)})):old(path,options));await act(async()=>{auth.suspend();await auth.bootstrap()})}
  else await act(async()=>auth.lock())
  await act(async()=>finish(response({items:sources(),next_after:null})));expect(document.querySelector('.wb-workspace')).toBeNull();expect(document.body.innerHTML).not.toMatch(/78000000|1,500|2026-05/)
})
it.each(['Source records','Batch receipts'] as const)('clears displayed %s when an idle session check detects replacement',async label=>{
  await openActivity();await action(label);const previous=fetchMock.getMockImplementation()!;fetchMock.mockImplementation((path,options)=>path==='/api/v1/auth/session'?Promise.resolve(response({...session(),workspace_context:'e'.repeat(64)})):previous(path,options));await act(async()=>auth.check());expect(auth.snapshot().screen).toMatchObject({kind:'blocked',reason:'context'});expect(document.querySelector('.wb-workspace')).toBeNull()
})
