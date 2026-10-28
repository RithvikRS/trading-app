import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import axe from 'axe-core'
import Workspace from '../../workspace/src/Workspace'
import ReceiptInspection from '../../workspace/src/ReceiptInspection'
import { AuthController } from '../../workspace/src/auth'
import { bankAccount, bankHistory } from '../../workspace/src/banking-evidence'
import { eventEvidence, eventIdentity } from '../../workspace/src/activity-evidence'
import { bankProvenance } from '../../workspace/src/bank-provenance'
import type { BankProvenance } from '../../workspace/src/bank-provenance'
import { bankComparison } from '../../workspace/src/bank-comparison-evidence'
import { bankInputPage } from '../../workspace/src/bank-input-evidence'
import { emptyInputProgress } from '../../workspace/src/input-evidence'
import type { InputSelection } from '../../workspace/src/input-evidence'
import { receiptPage, savedReceipt } from '../../workspace/src/receipt-evidence'
import type { NativeComparison, NativeScope } from '../../workspace/src/comparison-evidence'
import type { Account } from '../../workspace/src/accounts'

const id = (n: number) => `81000000-0000-4000-8000-${String(n).padStart(12, '0')}`
const account: Account = { id: id(1), kind: 'bank', institution: 'hdfc', market: 'IN', label: 'Everyday account', currencies: ['INR', 'USD'], revision: 1, state: 'active' }
const event = () => ({ id: id(30), account_id: id(1), position_id: null, instrument_id: null, kind: 'cash_movement', revision: 2, is_current: true, account_state: 'active', status: 'active', posting_state: 'posted', correction_reason: 'source_correction', trade_date: null, settlement_date: null, booking_date: '2026-05-04', value_date: '2026-05-05', source_row_id: id(10), source_review_revision: 2, source_id: id(11), observation_id: id(12), batch_id: id(13), coverage: 'complete_activity', period_start: '2026-05-01', period_end: '2026-05-31', cash_date_basis: 'value', components: [{role:'net_cash',source:'-1500.00',currency:'INR',missing_reason:null}] })
const context = () => bankProvenance(bankAccount(account), eventEvidence(event(), account.id))
const receipt = () => ({ id:id(80),batch_id:id(13),batch_revision:2,mode:'reconciled',coverage:'complete_activity',created_at:'2026-10-25T10:11:12Z',row_count:20,selection_count:1,scope_count:4 })
const metadata = (scopeCount = 4, rowCount = 20) => savedReceipt({...receipt(),scope_count:scopeCount,row_count:rowCount},context().origin)
const scope = (n=100, owner=account.id, currency: 'INR'|'USD'='INR'):NativeScope => ({id:id(n),receipt_id:id(80),kind:'cash',account_id:owner,position_id:null,currency,period_start:'2026-05-01',period_end:'2026-05-31',date_basis:'value',rule_version:1,input_count:9})
const scopes = () => [scope(),scope(101,account.id,'USD'),scope(102,id(21),'USD'),{...scope(103,id(21)),kind:'units' as const,position_id:id(22),currency:null,date_basis:'trade' as const}]
const comparison = (selected=scope()) => ({scope:selected,source:{outcome:'balanced',opening:'1000.00',posted_total:'-125.50',closing:'874.50',calculated_closing:'874.50',difference:'0.00',posted_count:2,pending_count:1},combined:{outcome:'balanced',opening:'1000',posted_total:'-125.5',closing:'874.5',calculated_closing:'874.50',difference:'-0.00',posted_count:1,pending_count:1}})
function counted(posted:number,pending:number,combinedPosted=1,combinedPending=1,currency:'INR'|'USD'='INR') {const selected={...scope(100,account.id,currency),input_count:4+posted+pending+combinedPosted+combinedPending};const value=comparison(selected),zero={outcome:'balanced',opening:'1000.00',posted_total:'0.00',closing:'1000.00',calculated_closing:'1000.00',difference:'0.00'};return {...value,source:{...zero,posted_count:posted,pending_count:pending},combined:{...zero,posted_count:combinedPosted,pending_count:combinedPending}}}
const session = () => ({status:'authenticated',workspace_context:'f'.repeat(64),expires_at:new Date(Date.now()+28_800_000).toISOString(),idle_expires_at:new Date(Date.now()+900_000).toISOString(),fresh_until:new Date(Date.now()+300_000).toISOString(),factors:[id(99)],unverified_factors:[]})
const response=(data:unknown,status=200)=>new Response(JSON.stringify(data),{status,headers:{'Content-Type':'application/json','Cache-Control':'no-store',Date:new Date().toUTCString()}})
const fetchMock=vi.fn<typeof fetch>();let auth:AuthController,masked:boolean,theme:string,currency:string,revision:number
beforeEach(()=>{masked=false;theme='light';currency='INR';revision=1;document.cookie='trading_dev_csrf=synthetic-csrf-value-long-enough; Path=/';vi.stubGlobal('fetch',fetchMock);fetchMock.mockReset();auth=new AuthController();fetchMock.mockImplementation(async(path,options)=>{
 if(path==='/api/v1/auth/bootstrap')return response({status:'ready',recovery_email_enabled:false})
 if(path==='/api/v1/auth/session')return response(session())
 if(path==='/api/v1/auth/logout')return response({status:'signed_out',provider_cleanup:'complete'})
 if(path==='/api/v1/preferences'){if(options?.method==='PUT'){const b=JSON.parse(String(options.body));masked=b.amount_masked;theme=b.theme;currency=b.display_currency;revision++}return response({amount_masked:masked,theme,display_currency:currency,revision})}
 if(path==='/api/v1/finance/accounts/query')return response({items:[account],next_after:null})
 if(path==='/api/v1/finance/events/query')return response({items:[event()],next_after:null})
 if(path==='/api/v1/finance/events/history')return response({items:[event(),{...event(),revision:1,is_current:false,correction_reason:null}],next_before:null})
 if(path==='/api/v1/finance/receipts/query')return response({items:[receipt()],next_after:null})
 if(path==='/api/v1/finance/receipts/scopes/query')return response({items:scopes(),next_after:null})
 if(path==='/api/v1/finance/receipts/scopes/inspect'){const selected=scopes().find(s=>s.id===JSON.parse(String(options!.body)).id)!;return response(comparison(selected))}
 if(path==='/api/v1/finance/receipts/inputs/query'){const body=JSON.parse(String(options!.body));const selected=scopes().find(s=>s.id===body.scope_id)!;return response({items:inputRows(saved(selected),body),next_after:null})}
 return response({},404)
})})
afterEach(()=>{auth.lock();vi.unstubAllGlobals();document.cookie='trading_dev_csrf=; Max-Age=0; Path=/';delete document.documentElement.dataset.theme})
function override(path:string,handler:(body:Record<string,unknown>)=>unknown,status=200){const old=fetchMock.getMockImplementation()!;fetchMock.mockImplementation((url,options)=>url===path?Promise.resolve(response(handler(JSON.parse(String(options!.body))),status)):old(url,options))}
const calls=()=>fetchMock.mock.calls.filter(([p])=>String(p).includes('/finance/'))
async function openActivity(){render(<Workspace controller={auth}/>);await screen.findByRole('heading',{name:'A fresh start.'});fireEvent.click(within(screen.getByRole('navigation',{name:'Workspace navigation'})).getByRole('button',{name:'Banking'}));fireEvent.click(await screen.findByRole('button',{name:'View saved activity for HDFC Everyday account'}));await screen.findByRole('heading',{name:'Saved account activity'})}
async function receipts(rev=2){const button=screen.getByLabelText(`Batch receipts for event ${id(30)}, revision ${rev}`);const details=button.closest('details')!;if(!details.open)fireEvent.click(within(details).getByText('Source details'));fireEvent.click(button);await screen.findByRole('heading',{name:'Batch completion'})}
async function openScopes(){await openActivity();await receipts();fireEvent.click(screen.getByRole('button',{name:'Saved comparisons'}));await screen.findByRole('heading',{name:'Saved comparisons'})}
async function inspect(native='INR cash'){const card=screen.getAllByRole('article',{name:`${native} from 2026-05-01 to 2026-05-31`}).find(card=>within(card).queryByText('This bank account'))!;fireEvent.click(within(card).getByRole('button',{name:'Inspect comparison'}));await screen.findByRole('heading',{name:`${native} comparison`})}


const saved = (selected = scope()) => bankComparison(comparison(selected), selected, metadata(), context())
const selection: InputSelection = { side: 'source', part: 'activity' }
function inputRows(value: NativeComparison = saved(), chosen: InputSelection = selection) {
  const side = value[chosen.side], activity = chosen.part === 'activity', count = activity ? side.posted_count + side.pending_count : 1
  return Array.from({ length: count }, (_, index) => {
    const posted = index < side.posted_count, reference = id((chosen.side === 'source' ? 300 : 600) + (chosen.part === 'opening' ? -100 : chosen.part === 'closing' ? -99 : index))
    return { id: reference, scope_id: value.scope.id, side: chosen.side, part: chosen.part, reference_revision: 2,
      source_row_id: chosen.side === 'source' ? reference : null, event_id: chosen.side === 'combined' && activity ? reference : null, snapshot_id: chosen.side === 'combined' && !activity ? reference : null,
      source: activity ? posted ? index === 0 ? side.posted_total : '-0.00' : '7.00' : side[chosen.part as 'opening' | 'closing'],
      evidence_date: chosen.part === 'opening' ? value.scope.period_start : chosen.part === 'closing' ? value.scope.period_end : posted ? value.scope.period_start : null,
      posting_state: activity ? posted ? 'posted' as const : 'pending' as const : null, kind: value.scope.kind, currency: value.scope.currency }
  })
}
const page = (items = inputRows()) => ({ items, next_after: null })
async function openInputs(chosen: InputSelection = selection, native = 'INR cash') {
  await openScopes(); await inspect(native)
  fireEvent.click(screen.getByRole('button', { name: `${chosen.side === 'source' ? 'Source report' : 'Combined saved evidence'}: ${chosen.part} inputs` }))
  await screen.findByRole('heading', { name: 'Frozen inputs' })
}
const selections: InputSelection[] = ['source', 'combined'].flatMap(side => ['opening', 'activity', 'closing'].map(part => ({ side, part } as InputSelection)))

it.each(selections)('preserves the exact retained $side $part bank inputs', chosen => {
  const rows = inputRows(saved(), chosen), parsed = bankInputPage(page(rows), saved(), metadata(), context(), chosen)
  expect(parsed.items).toEqual(rows)
  expect(parsed.progress.count).toBe(rows.length)
  expect(parsed.items.every(row => row.kind === 'cash' && row.currency === 'INR')).toBe(true)
})
it.each(['INR', 'USD'] as const)('binds the selected native %s bank scope', currency => {
  const selected = scope(100, account.id, currency), value = saved(selected)
  expect(bankInputPage(page(inputRows(value)), value, metadata(), context(), selection).items[0]?.currency).toBe(currency)
  const narrowed = { ...context(), account: { ...context().account, currencies: ['INR'] as ('INR' | 'USD')[] } }
  if (currency === 'USD') expect(() => bankInputPage(page(inputRows(value)), value, metadata(), narrowed, selection)).toThrow()
})
it.each([
  { account_id: id(99) }, { kind: 'units', position_id: id(2), currency: null, date_basis: 'trade' },
  { position_id: id(2) }, { currency: null }, { period_start: '2026-04-01' }, { period_end: '2026-06-01' },
  { date_basis: 'booking' }, { receipt_id: id(99) },
])('rejects a comparison outside the retained bank context %#', change => {
  const value = { ...saved(), scope: { ...scope(), ...change } } as NativeComparison
  expect(() => bankInputPage(page(), value, metadata(), context(), selection)).toThrow()
})
it.each([{ kind: 'lot' }, { coverage: 'unknown' }, { status: 'cancelled' }, { posting_state: 'unknown' }, { native_currency: null }, { period_start: null }, { cash_date_basis: 'trade' }])('rejects an incompatible origin before input display %#', change => {
  const altered = { ...context(), origin: { ...context().origin, ...change } } as BankProvenance
  expect(() => bankInputPage(page(), saved(), metadata(), altered, selection)).toThrow()
})
it.each([
  { scope_id: id(99) }, { kind: 'units' }, { currency: 'USD' }, { side: 'combined' }, { part: 'closing' },
  { source: null }, { source: '0.001' }, { source: '1e3' }, { source: 0 }, { source: '01.00' },
  { evidence_date: '2026-04-30' }, { evidence_date: null }, { posting_state: null },
  { source_row_id: id(99) }, { event_id: id(30) }, { snapshot_id: id(50) }, { reference_revision: 0 }, { extra: 'unexpected' },
])('rejects the entire page for invalid input evidence %#', change => {
  const items = inputRows(); items[0] = { ...items[0]!, ...change } as typeof items[number]
  expect(() => bankInputPage(page(items), saved(), metadata(), context(), selection)).toThrow()
})
it('preserves negative zero, source spelling and date-free pending evidence', () => {
  const parsed = bankInputPage(page(), saved(), metadata(), context(), selection)
  expect(parsed.items.map(row => row.source)).toEqual(['-125.50', '-0.00', '7.00'])
  expect(parsed.items[2]).toMatchObject({ posting_state: 'pending', evidence_date: null })
  const missing = inputRows(); delete (missing[1] as Partial<typeof missing[number]>).source
  expect(() => bankInputPage(page(missing), saved(), metadata(), context(), selection)).toThrow()
})
it('binds originating source and combined event revisions without inferring membership', () => {
  const source = inputRows(); source[0] = { ...source[0]!, id: context().origin.source_row_id, source_row_id: context().origin.source_row_id }
  expect(bankInputPage(page(source), saved(), metadata(), context(), selection).items[0]?.reference_revision).toBe(2)
  source[0]!.reference_revision = 1
  expect(() => bankInputPage(page(source), saved(), metadata(), context(), selection)).toThrow()
  const chosen: InputSelection = { side: 'combined', part: 'activity' }, combined = inputRows(saved(), chosen)
  combined[0] = { ...combined[0]!, id: context().origin.id, event_id: context().origin.id }
  expect(bankInputPage(page(combined), saved(), metadata(), context(), chosen).items[0]?.reference_revision).toBe(2)
  combined[0]!.reference_revision = 1
  expect(() => bankInputPage(page(combined), saved(), metadata(), context(), chosen)).toThrow()
})
it('checks checkpoint spelling and dates independently for each side', () => {
  for (const chosen of selections.filter(row => row.part !== 'activity')) {
    const items = inputRows(saved(), chosen)
    expect(bankInputPage(page(items), saved(), metadata(), context(), chosen).items[0]?.source).toBe(saved()[chosen.side][chosen.part as 'opening' | 'closing'])
    items[0]!.evidence_date = '2026-05-15'
    expect(() => bankInputPage(page(items), saved(), metadata(), context(), chosen)).toThrow()
  }
  const chosen: InputSelection = { side: 'source', part: 'opening' }, items = inputRows(saved(), chosen)
  items[0]!.source = '1000'
  expect(() => bankInputPage(page(items), saved(), metadata(), context(), chosen)).toThrow()
})
it('keeps bounded page counts, posted/pending totals and cursors separate', () => {
  const raw = counted(25, 1, 1, 0), value = bankComparison(raw, raw.scope, metadata(1, 100), context()), items = inputRows(value)
  const first = bankInputPage({ items: items.slice(0, 25), next_after: items[24]!.id }, value, metadata(1, 100), context(), selection)
  expect(first.progress).toEqual({ count: 25, posted: 25, pending: 0 })
  const last = bankInputPage({ items: items.slice(25), next_after: null }, value, metadata(1, 100), context(), selection, first.next_after, first.progress)
  expect(last.progress).toEqual({ count: 26, posted: 25, pending: 1 })
  expect(() => bankInputPage({ items: [], next_after: null }, value, metadata(1, 100), context(), selection, first.next_after, first.progress)).toThrow()
  expect(() => bankInputPage({ items: items.slice(25), next_after: null }, value, metadata(1, 100), context(), selection, first.next_after, emptyInputProgress)).toThrow()
  expect(() => bankInputPage({ items: items.slice(0, 25), next_after: null }, value, metadata(1, 100), context(), selection)).toThrow()
})
it('retains genuine empty combined activity without creating a zero record', () => {
  const raw = counted(1, 0, 0, 0), value = bankComparison(raw, raw.scope, metadata(1), context()), chosen: InputSelection = { side: 'combined', part: 'activity' }
  expect(bankInputPage(page([]), value, metadata(1), context(), chosen).items).toEqual([])
  expect(() => bankInputPage(page([]), value, metadata(1), context(), { side: 'combined', part: 'opening' })).toThrow()
})
it.each(selections)('opens only the explicitly selected $side $part input page', async chosen => {
  await openInputs(chosen)
  await waitFor(() => expect(document.activeElement).toBe(screen.getByRole('heading', { name: 'Frozen inputs' })))
  expect((screen.getByLabelText('Evidence side') as HTMLSelectElement).value).toBe(chosen.side)
  expect((screen.getByLabelText('Input group') as HTMLSelectElement).value).toBe(chosen.part)
  const requests = calls().filter(([path]) => String(path).includes('/receipts/inputs/'))
  expect(requests).toHaveLength(1)
  expect(JSON.parse(String(requests[0]![1]!.body))).toEqual({ scope_id: id(100), side: chosen.side, part: chosen.part, limit: 25, after: null })
  expect(screen.getByText(/Later corrections or selections do not replace it/)).toBeTruthy()
})
it('changes input groups and sides explicitly, refreshes and returns to the same comparison', async () => {
  await openInputs()
  fireEvent.change(screen.getByLabelText('Evidence side'), { target: { value: 'combined' } })
  await screen.findByRole('heading', { name: 'Combined saved evidence · Activity' })
  fireEvent.change(screen.getByLabelText('Input group'), { target: { value: 'closing' } })
  await screen.findByRole('heading', { name: 'Combined saved evidence · Closing' })
  expect(screen.getByText('INR 874.5')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: 'Refresh inputs' })); await screen.findByRole('heading', { name: 'Frozen inputs' })
  expect(JSON.parse(String(calls().at(-1)![1]!.body))).toMatchObject({ scope_id: id(100), side: 'combined', part: 'closing', after: null })
  fireEvent.click(screen.getByRole('button', { name: 'Back to comparison' })); await screen.findByRole('heading', { name: 'INR cash comparison' })
  expect(JSON.parse(String(calls().at(-1)![1]!.body))).toEqual({ id: id(100) })
})
it.each(['INR cash', 'USD cash'])('keeps %s inputs native across display preference changes', async native => {
  await openInputs(selection, native)
  const before = calls().length
  fireEvent.change(screen.getByLabelText('Display currency'), { target: { value: 'USD' } }); fireEvent.click(screen.getByRole('button', { name: 'Save preferences' }))
  await screen.findByText('Saved to your account'); expect(calls()).toHaveLength(before)
  expect(screen.getByText(`${native.startsWith('INR') ? 'INR' : 'USD'} -125.50`)).toBeTruthy()
})
it.each([404, 409, 500])('clears bank context after unavailable input status %s and restarts at the directory', async status => {
  await openScopes(); await inspect()
  override('/api/v1/finance/receipts/inputs/query', () => ({ detail: 'private failure' }), status)
  fireEvent.click(screen.getByRole('button', { name: 'Source report: activity inputs' }))
  await screen.findByRole('alert'); expect(document.querySelector('.wi-receipts')).toBeNull()
  expect(document.body.innerHTML).not.toMatch(/874\.50|1000\.00|private failure/)
  fireEvent.click(screen.getByRole('button', { name: 'Reload saved bank accounts' }))
  await screen.findByRole('heading', { name: 'Your bank accounts' })
  expect(JSON.parse(String(calls().at(-1)![1]!.body))).toEqual({ limit: 25, after: null })
})
it('locks the workspace for an unverified input page before showing any partial values', async () => {
  await openScopes(); await inspect()
  const items = inputRows(); items[2]!.currency = 'USD'
  override('/api/v1/finance/receipts/inputs/query', () => page(items))
  fireEvent.click(screen.getByRole('button', { name: 'Source report: activity inputs' }))
  await screen.findByRole('heading', { name: 'Unable to verify this response.' })
  expect(document.querySelector('.wb-workspace')).toBeNull()
  expect(document.body.innerHTML).not.toMatch(/125\.50|7\.00/)
})
it.each(['navigate', 'logout', 'lock', 'context'])('discards late inputs after %s', async reason => {
  await openScopes(); await inspect()
  let finish!: (response: Response) => void
  const previous = fetchMock.getMockImplementation()!
  fetchMock.mockImplementation((path, options) => path === '/api/v1/finance/receipts/inputs/query' ? new Promise(resolve => { finish = resolve }) : previous(path, options))
  fireEvent.click(screen.getByRole('button', { name: 'Source report: activity inputs' }))
  await screen.findByText('Checking saved completion evidence…')
  expect(document.body.innerHTML).not.toMatch(/874\.50|1000\.00/)
  if (reason === 'navigate') fireEvent.click(within(screen.getByRole('navigation', { name: 'Workspace navigation' })).getByRole('button', { name: 'Overview' }))
  else if (reason === 'logout') fireEvent.click(screen.getByRole('button', { name: 'Sign out here' }))
  else if (reason === 'lock') await act(async () => auth.lock())
  else { fetchMock.mockImplementation((path, options) => path === '/api/v1/auth/session' ? Promise.resolve(response({ ...session(), workspace_context: 'e'.repeat(64) })) : previous(path, options)); await act(async () => { auth.suspend(); await auth.bootstrap() }) }
  await act(async () => finish(response(page())))
  expect(document.querySelector('.wb-workspace')).toBeNull(); expect(document.body.innerHTML).not.toMatch(/125\.50|7\.00/)
})
it.each(['light', 'dark'])('masks input values and retains keyboard and accessibility support in %s', async mode => {
  theme = mode; masked = true; await openScopes(); await inspect()
  const user = userEvent.setup(), action = screen.getByRole('button', { name: 'Source report: activity inputs' })
  await waitFor(() => expect((action as HTMLButtonElement).disabled).toBe(false)); action.focus(); expect(document.activeElement).toBe(action); await user.keyboard('{Enter}')
  expect(document.activeElement).toBe(await screen.findByRole('heading', { name: 'Frozen inputs' }))
  expect(screen.getAllByText('••••')).toHaveLength(3)
  expect(document.querySelector('.wb-workspace')!.innerHTML).not.toMatch(/125\.50|-0\.00|7\.00/)
  expect((await axe.run(document.querySelector('.wb-workspace')!, { rules: { 'color-contrast': { enabled: false }, region: { enabled: false } } })).violations).toEqual([])
})
it('keeps row-effects-only navigation without comparison or input controls', async () => {
  await auth.bootstrap(); render(<section><h2>Saved evidence</h2><ReceiptInspection auth={auth} context={context().origin} initial={receiptPage({ items: [receipt()], next_after: null }, context().origin)} masked={false} busy={false} navigation={{ mode: 'row-effects', onUnavailable: () => {}, backLabel: 'saved activity' }} onBack={() => {}} /></section>)
  expect(screen.queryByRole('button', { name: 'Saved comparisons' })).toBeNull()
  expect(screen.queryByRole('button', { name: /inputs$/ })).toBeNull()
})
it('uses only fixed bounded read routes without persisting any input data', async () => {
  const storage = vi.spyOn(Storage.prototype, 'setItem'); await openInputs()
  for (const [path, options] of calls()) {
    expect(options).toMatchObject({ method: 'POST', credentials: 'same-origin', cache: 'no-store', redirect: 'error' })
    expect(String(path)).not.toMatch(/snapshots|provider|complete|select/)
    const body = JSON.parse(String(options!.body)); if (String(path).endsWith('/inputs/query')) expect(body).toEqual({ scope_id: id(100), side: 'source', part: 'activity', limit: 25, after: null })
  }
  expect(storage).not.toHaveBeenCalled(); storage.mockRestore()
})

it('remembers the highest accepted bank head without changing the clicked event identity', () => {
  const root = eventIdentity(eventEvidence(event(), account.id)), original = structuredClone(root)
  const page = { items: [{ ...event(), revision: 3 }, { ...event(), is_current: false }], next_before: null }
  expect(bankHistory(page, bankAccount(account), root, null, 2).items[0]?.revision).toBe(3)
  expect(() => bankHistory({ items: [event()], next_before: null }, bankAccount(account), root, null, 3)).toThrow()
  expect(bankHistory({ items: [{ ...event(), is_current: false }], next_before: null }, bankAccount(account), root, 3, 3).items[0]?.revision).toBe(2)
  expect(root).toEqual(original)
  const selected = eventEvidence({ ...event(), revision: 1, correction_reason: null, is_current: false }, account.id)
  const retained = bankProvenance(bankAccount(account), selected, root, 3)
  expect(retained.origin.revision).toBe(1)
  expect(retained.back).toEqual({ kind: 'history', root: original, highestSeenRevision: 3 })
})
it.each([0, 1, 2.5, Number.POSITIVE_INFINITY, Number.MAX_SAFE_INTEGER + 1])('rejects an invalid highest-seen history revision %s', highest => {
  const root = eventIdentity(eventEvidence(event(), account.id))
  expect(() => bankHistory({ items: [event()], next_before: null }, bankAccount(account), root, null, highest)).toThrow()
  expect(() => bankProvenance(bankAccount(account), eventEvidence(event(), account.id), root, highest)).toThrow()
})
it('rejects a regressed head after refreshing a history page that first advanced beyond the clicked revision', async () => {
  override('/api/v1/finance/events/history', () => ({ items: [{ ...event(), revision: 3 }, { ...event(), is_current: false }], next_before: null }))
  await openActivity(); fireEvent.click(screen.getByRole('button', { name: `Revision history for event ${id(30)}` }))
  await screen.findByRole('heading', { name: 'Event revision history' })
  override('/api/v1/finance/events/history', () => ({ items: [event()], next_before: null }))
  fireEvent.click(screen.getByRole('button', { name: 'Refresh revisions' }))
  await screen.findByRole('heading', { name: 'Unable to verify this response.' })
  expect(document.querySelector('.wb-workspace')).toBeNull()
})
it('retains the highest bank head through earlier pages and latest-page navigation', async () => {
  const revision = (n: number, current = false) => ({ ...event(), revision: n, is_current: current, correction_reason: n === 1 ? null : 'source_correction' })
  override('/api/v1/finance/events/history', body => body.before === null ? { items: Array.from({ length: 25 }, (_, n) => revision(30 - n, n === 0)), next_before: 6 } : { items: Array.from({ length: 5 }, (_, n) => revision(5 - n)), next_before: null })
  await openActivity(); fireEvent.click(screen.getByRole('button', { name: `Revision history for event ${id(30)}` }))
  await screen.findByRole('heading', { name: 'Event revision history' })
  fireEvent.click(screen.getByRole('button', { name: 'Earlier revisions' })); await screen.findByText(/Earlier retained revision 5/)
  fireEvent.click(screen.getByRole('button', { name: 'Refresh revisions' })); await screen.findByText(/Earlier retained revision 5/)
  override('/api/v1/finance/events/history', () => ({ items: [event()], next_before: null }))
  fireEvent.click(screen.getByRole('button', { name: 'Latest revisions' }))
  await screen.findByRole('heading', { name: 'Unable to verify this response.' })
})
it.each(['source', 'receipt'])('retains the highest bank head across %s inspection and return', async route => {
  override('/api/v1/finance/events/history', () => ({ items: [{ ...event(), revision: 3 }, { ...event(), is_current: false }], next_before: null }))
  override('/api/v1/finance/imports/observations/query', () => ({ items: [{ id: id(12), source_id: id(11), previous_id: null, is_current: true, coverage: 'complete_activity', period_start: '2026-05-01', period_end: '2026-05-31' }], next_after: null }))
  await openActivity(); fireEvent.click(screen.getByRole('button', { name: `Revision history for event ${id(30)}` }))
  await screen.findByRole('heading', { name: 'Event revision history' })
  const action = screen.getByLabelText(`${route === 'source' ? 'Source records' : 'Batch receipts'} for event ${id(30)}, revision 2`)
  action.closest('details')!.open = true; fireEvent.click(action)
  if (route === 'source') await screen.findByRole('heading', { name: 'Source records' })
  else {
    await screen.findByRole('heading', { name: 'Batch completion' }); fireEvent.click(screen.getByRole('button', { name: 'Saved comparisons' })); await screen.findByRole('heading', { name: 'Saved comparisons' }); await inspect()
    fireEvent.click(screen.getByRole('button', { name: 'Source report: activity inputs' })); await screen.findByRole('heading', { name: 'Frozen inputs' })
    fireEvent.click(screen.getByRole('button', { name: 'Back to comparison' })); await screen.findByRole('heading', { name: 'INR cash comparison' })
    fireEvent.click(screen.getByRole('button', { name: 'Back to comparisons' })); await screen.findByRole('heading', { name: 'Saved comparisons' })
    fireEvent.click(screen.getByRole('button', { name: 'Back to receipts' })); await screen.findByRole('heading', { name: 'Batch completion' })
  }
  override('/api/v1/finance/events/history', () => ({ items: [event()], next_before: null }))
  fireEvent.click(screen.getByRole('button', { name: 'Back to revision history' }))
  await screen.findByRole('heading', { name: 'Unable to verify this response.' })
})
it('continues to accept a stable or higher retained history head', async () => {
  let highest = 3
  override('/api/v1/finance/events/history', () => ({ items: [{ ...event(), revision: highest }, { ...event(), is_current: false }], next_before: null }))
  await openActivity(); fireEvent.click(screen.getByRole('button', { name: `Revision history for event ${id(30)}` }))
  await screen.findByRole('heading', { name: 'Event revision history' }); fireEvent.click(screen.getByRole('button', { name: 'Refresh revisions' })); await screen.findByText(/Latest retained revision 3/)
  highest = 4; fireEvent.click(screen.getByRole('button', { name: 'Refresh revisions' })); await screen.findByText(/Latest retained revision 4/)
  expect(screen.queryByRole('heading', { name: 'Unable to verify this response.' })).toBeNull()
})
it('pages and refreshes saved inputs without accumulating earlier financial values', async () => {
  const raw = counted(25, 1, 1, 0), value = bankComparison(raw, raw.scope, metadata(1, 100), context()), items = inputRows(value)
  override('/api/v1/finance/receipts/query', () => ({ items: [{ ...receipt(), row_count: 100, scope_count: 1 }], next_after: null }))
  override('/api/v1/finance/receipts/scopes/query', () => ({ items: [raw.scope], next_after: null }))
  override('/api/v1/finance/receipts/scopes/inspect', () => raw)
  override('/api/v1/finance/receipts/inputs/query', body => body.after === null ? { items: items.slice(0, 25), next_after: items[24]!.id } : { items: items.slice(25), next_after: null })
  await openInputs(); expect(document.querySelectorAll('.wi-inputs .wi-evidence')).toHaveLength(25)
  fireEvent.click(screen.getByRole('button', { name: 'Next input page' })); await screen.findByText('INR 7.00')
  expect(document.querySelectorAll('.wi-inputs .wi-evidence')).toHaveLength(1)
  fireEvent.click(screen.getByRole('button', { name: 'Refresh inputs' })); await screen.findByText('INR 7.00')
  expect(JSON.parse(String(calls().at(-1)![1]!.body)).after).toBe(items[24]!.id)
  fireEvent.click(screen.getByRole('button', { name: 'First input page' })); await screen.findByText('INR 0.00')
  expect(document.querySelectorAll('.wi-inputs .wi-evidence')).toHaveLength(25)
})
it('allows archived-bank input inspection without treating it as a current balance', async () => {
  override('/api/v1/finance/accounts/query', () => ({ items: [{ ...account, state: 'archived' }], next_after: null }))
  override('/api/v1/finance/events/query', () => ({ items: [{ ...event(), account_state: 'archived' }], next_after: null }))
  await openInputs({ side: 'combined', part: 'opening' })
  expect(screen.getByText('INR 1,000')).toBeTruthy()
  expect(screen.getByText(/no current balance is calculated/)).toBeTruthy()
})
