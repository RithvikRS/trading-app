import { StrictMode } from 'react'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import axe from 'axe-core'
import Workspace from '../../workspace/src/Workspace'
import { AuthController } from '../../workspace/src/auth'
import { cashChoiceFixture as choice, cashSnapshotFixture as snapshot, cancelledCashFixture, cashTestBank as bank, cashTestId as id } from './bank-cash-fixtures'

const routes = {
  accounts: '/api/v1/finance/accounts/query', choices: '/api/v1/finance/snapshots/selections/query',
  resolve: '/api/v1/finance/snapshots/selections/resolve', history: '/api/v1/finance/snapshots/selections/history', snapshots: '/api/v1/finance/snapshots/history',
} as const
const session = () => ({ status: 'authenticated', workspace_context: 'f'.repeat(64), expires_at: new Date(Date.now() + 28_800_000).toISOString(), idle_expires_at: new Date(Date.now() + 900_000).toISOString(), fresh_until: new Date(Date.now() + 300_000).toISOString(), factors: [id(99)], unverified_factors: [] })
const response = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store', Date: new Date().toUTCString() } })
const cash = (source: string, currency = 'INR') => [{ role: 'net_cash', source, currency, missing_reason: null }]
const selected = (selection = choice(), evidence = snapshot()) => ({ selection, state: 'selected', snapshot: evidence })
function historyPage<T>(head: number, before: unknown, item: (revision: number, current: boolean) => T) {
  const first = typeof before === 'number' ? before - 1 : head
  const last = Math.max(1, first - 24)
  return { items: Array.from({ length: Math.max(0, first - last + 1) }, (_, offset) => item(first - offset, first - offset === head)), next_before: last > 1 ? last : null }
}
const choicePage = (head = 2, before: unknown = null) => historyPage(head, before, (revision, is_current) => choice(revision, { is_current }))
const snapshotPage = (head = 3, before: unknown = null, changes: Record<string, unknown> = {}) => historyPage(head, before, (revision, is_current) => snapshot(revision, { is_current, ...changes }))
const fetchMock = vi.fn<typeof fetch>()
let auth: AuthController, masked: boolean, currency: string, theme: string, preferenceRevision: number

beforeEach(() => {
  masked = false; currency = 'INR'; theme = 'light'; preferenceRevision = 1
  localStorage.clear(); sessionStorage.clear()
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
    if (path === routes.accounts) return response({ items: [bank], next_after: null })
    if (path === routes.choices) return response({ items: [choice()], next_after: null })
    if (path === routes.resolve) return response(selected())
    if (path === routes.history) return response(choicePage(2, JSON.parse(String(options!.body)).before))
    if (path === routes.snapshots) return response(snapshotPage(3, JSON.parse(String(options!.body)).before))
    return response({}, 404)
  })
})
afterEach(() => { auth.lock(); vi.unstubAllGlobals(); document.cookie = 'trading_dev_csrf=; Max-Age=0; Path=/'; delete document.documentElement.dataset.theme })

function override(path: string, handler: (body: Record<string, unknown>) => unknown, status = 200) {
  const previous = fetchMock.getMockImplementation()!
  fetchMock.mockImplementation((url, options) => url === path ? Promise.resolve(response(handler(JSON.parse(String(options!.body))), status)) : previous(url, options))
}
function defer(path: string) {
  let finish!: (value: Response) => void
  const previous = fetchMock.getMockImplementation()!
  fetchMock.mockImplementation((url, options) => url === path ? new Promise(resolve => { finish = resolve }) : previous(url, options))
  return (data: unknown, status = 200) => finish(response(data, status))
}
const calls = (route?: string) => fetchMock.mock.calls.filter(([path]) => route ? path === route : String(path).includes('/finance/'))
const bodies = (route: string) => calls(route).map(([, options]) => JSON.parse(String(options!.body)))
const click = (name: string) => fireEvent.click(screen.getByRole('button', { name }))
async function openBanking(strict = false) {
  const content = <Workspace controller={auth} />
  const mounted = render(strict ? <StrictMode>{content}</StrictMode> : content)
  await screen.findByRole('heading', { name: 'A fresh start.' })
  fireEvent.click(within(screen.getByRole('navigation', { name: 'Workspace navigation' })).getByRole('button', { name: 'Banking' }))
  await screen.findByRole('heading', { name: 'Saved bank accounts on this page' })
  return mounted
}
async function openCash(strict = false) {
  const mounted = await openBanking(strict)
  click('View saved cash for HDFC Everyday account')
  await screen.findByRole('heading', { name: 'Inspect a native cash choice' })
  return mounted
}
async function submit(currency = 'INR', heading = 'Selected cash snapshot') {
  fireEvent.change(screen.getByLabelText('Native currency'), { target: { value: currency } })
  click('View saved cash choice')
  return screen.findByRole('heading', { name: heading })
}
async function openSelected() { const mounted = await openCash(); await submit(); return mounted }
async function blocked() {
  await screen.findByRole('heading', { name: 'Unable to verify this response.' })
  expect(auth.snapshot().screen).toMatchObject({ kind: 'blocked', reason: 'protocol' })
  expect(document.querySelector('.wb-cash')).toBeNull()
  expect(document.body.innerHTML).not.toMatch(/12,345|12345|98,765|98765/)
}

it('requires an explicit native choice before reading selected cash, including StrictMode replay', async () => {
  await openCash(true)
  expect(calls().map(([path]) => path)).toEqual([routes.accounts])
  expect((screen.getByLabelText('Native currency') as HTMLSelectElement).value).toBe('')
  expect((screen.getByRole('button', { name: 'View saved cash choice' }) as HTMLButtonElement).disabled).toBe(true)
  await submit()
  expect(screen.getByText('INR 12,345.60')).toBeTruthy()
  expect(screen.getAllByText('2026-10-20T23:45:16.123456+05:30')).toHaveLength(2)
  expect(calls().map(([path]) => path)).toEqual([routes.accounts, routes.choices, routes.resolve])
  expect(bodies(routes.choices)).toEqual([{ account_id: bank.id, limit: 25, after: null }])
  expect(bodies(routes.resolve)).toEqual([{ id: id(20) }])
  expect(screen.getByText('Snapshot provenance · revision 3').closest('details')!.open).toBe(false)
  expect(screen.queryByText('Historical native cash')).toBeNull()
})

it('validates another declared currency before selecting INR and never treats it as INR absence', async () => {
  override(routes.choices, () => ({ items: [choice(), choice(1, { id: id(21), currency: 'USD', snapshot_id: id(31), snapshot_revision: 1 })], next_after: null }))
  await openSelected(); expect(screen.getByText('INR 12,345.60')).toBeTruthy(); expect(calls(routes.resolve)).toHaveLength(1)
})

it.each(['empty', 'only another native currency'])('distinguishes %s discovery from a saved zero and explicitly rechecks', async variant => {
  override(routes.choices, () => ({ items: variant === 'empty' ? [] : [choice(1, { currency: 'USD' })], next_after: null }))
  await openCash(); await submit('INR', 'No saved cash choice')
  expect(screen.getByText(/This does not establish zero cash/)).toBeTruthy()
  expect(screen.queryByText('Reported native cash')).toBeNull(); expect(calls(routes.resolve)).toHaveLength(0)
  override(routes.choices, () => ({ items: [choice()], next_after: null }))
  override(routes.resolve, () => selected(choice(), snapshot(3, { components: cash('-0.00') })))
  click('Check saved choices again'); await screen.findByText('INR -0.00')
  expect(calls(routes.choices)).toHaveLength(2)
})

it.each([
  ['stale', 'Saved cash choice needs review'], ['cancelled', 'Selected evidence is cancelled'],
  ['archived', 'Cash choice belongs to an archived account'], ['conflicting', 'Saved cash evidence conflicts'],
])('shows %s without a main amount while retaining an explicitly historical active pin', async (state, title) => {
  override(routes.resolve, () => ({ selection: choice(), state, snapshot: null }))
  if (state === 'archived') override(routes.snapshots, body => snapshotPage(3, body.before, { account_state: 'archived' }))
  await openCash(); await submit('INR', title)
  expect(screen.queryByText('Reported native cash')).toBeNull(); expect(screen.queryByText('INR 12,345.60')).toBeNull()
  if (state === 'stale') expect(screen.getByText(/does not describe the age of the report/)).toBeTruthy()
  click('Inspect pinned snapshot'); await screen.findByRole('heading', { name: 'Retained cash snapshot revisions' })
  expect(screen.getAllByText('Historical native cash')).toHaveLength(3)
  expect(screen.getAllByText('INR 12,345.60')).toHaveLength(3)
  expect(screen.getByText(/These retained amounts do not supply the selected cash view/)).toBeTruthy()
  expect(screen.queryByText('Reported native cash')).toBeNull()
  click('Back to saved cash'); await screen.findByRole('heading', { name: title })
  expect(screen.queryByText('INR 12,345.60')).toBeNull()
})

it.each(['unselected', 'stale'])('keeps archived-account %s resolver precedence without inventing a usable amount', async state => {
  override(routes.accounts, () => ({ items: [{ ...bank, state: 'archived', currencies: ['INR'] }], next_after: null }))
  const saved = state === 'unselected' ? choice(2, { reason: 'clear', snapshot_id: null, snapshot_revision: null }) : choice()
  override(routes.choices, () => ({ items: [saved], next_after: null }))
  override(routes.resolve, () => ({ selection: saved, state, snapshot: null }))
  await openCash(); expect((screen.getByLabelText('Native currency') as HTMLSelectElement).value).toBe('INR')
  click('View saved cash choice'); await screen.findByRole('heading', { name: state === 'unselected' ? 'Saved cash choice cleared' : 'Saved cash choice needs review' })
  expect(screen.getByText(/This bank account is archived/)).toBeTruthy()
  expect(screen.queryByText('Reported native cash')).toBeNull()
  expect(screen.queryByRole('button', { name: 'Inspect pinned snapshot' }) === null).toBe(state === 'unselected')
})

it('returns from a cleared choice through an older pinned choice without making historical amounts current', async () => {
  const cleared = choice(2, { reason: 'clear', snapshot_id: null, snapshot_revision: null })
  override(routes.choices, () => ({ items: [cleared], next_after: null }))
  override(routes.resolve, () => ({ selection: cleared, state: 'unselected', snapshot: null }))
  override(routes.history, () => ({ items: [cleared, choice(1, { is_current: false })], next_before: null }))
  await openCash(); await submit('INR', 'Saved cash choice cleared'); click('Choice history')
  await screen.findByRole('heading', { name: 'Cash choice history' })
  expect(screen.queryByRole('button', { name: 'Inspect pinned snapshot for choice revision 2' })).toBeNull()
  click('Inspect pinned snapshot for choice revision 1'); await screen.findByRole('heading', { name: 'Retained cash snapshot revisions' })
  expect(bodies(routes.snapshots)).toEqual([{ id: id(30), limit: 25, before: 4 }])
  click('Back to choice history'); await screen.findByRole('heading', { name: 'Cash choice history' })
  expect(screen.queryByText('Historical native cash')).toBeNull(); expect(calls(routes.history)).toHaveLength(2)
  click('Back to saved cash'); await screen.findByRole('heading', { name: 'Saved cash choice cleared' })
  expect(screen.queryByText('INR 12,345.60')).toBeNull()
})

it('shows cancellation without an invented zero and preserves earlier active evidence', async () => {
  const saved = choice(2, { snapshot_revision: 4 })
  override(routes.choices, () => ({ items: [saved], next_after: null }))
  override(routes.resolve, () => ({ selection: saved, state: 'cancelled', snapshot: null }))
  override(routes.snapshots, () => ({ items: [cancelledCashFixture(), ...snapshotPage(3).items.map(item => ({ ...item, is_current: false }))], next_before: null }))
  await openCash(); await submit('INR', 'Selected evidence is cancelled'); click('Inspect pinned snapshot')
  await screen.findByRole('heading', { name: 'Retained cash snapshot revisions' })
  expect(screen.getByText(/Cancelled snapshot. This revision has no amount/)).toBeTruthy()
  expect(screen.getAllByText('Historical native cash')).toHaveLength(3); expect(screen.queryByText('INR 0.00')).toBeNull()
})

it('keeps an older active pin historical when a later cancellation makes its choice stale', async () => {
  override(routes.resolve, () => ({ selection: choice(), state: 'stale', snapshot: null }))
  override(routes.snapshots, body => body.before === null
    ? { items: [cancelledCashFixture(), ...snapshotPage(4, 4).items], next_before: null }
    : snapshotPage(4, body.before))
  await openCash(); await submit('INR', 'Saved cash choice needs review')
  click('Inspect pinned snapshot'); await screen.findByRole('heading', { name: 'Snapshot revision 3' })
  expect(screen.queryByRole('heading', { name: 'Snapshot revision 4' })).toBeNull()
  expect(screen.getAllByText('Historical native cash')).toHaveLength(3)
  click('Latest snapshot revisions'); await screen.findByRole('heading', { name: 'Snapshot revision 4' })
  expect(screen.getByText(/Cancelled snapshot. This revision has no amount/)).toBeTruthy()
  click('Back to saved cash'); await screen.findByRole('heading', { name: 'Saved cash choice needs review' })
  expect(screen.queryByText('INR 12,345.60')).toBeNull()
})

it.each(['full_account', null])('preserves legal %s scope and an old source date without inventing freshness or completeness', async snapshot_scope => {
  override(routes.resolve, () => selected(choice(), snapshot(3, { snapshot_scope, as_of_date: '2020-01-02', as_of_instant: null, period_start: '2020-01-01', period_end: '2020-01-02' })))
  await openSelected(); expect(screen.getByText('INR 12,345.60')).toBeTruthy()
  expect(screen.getAllByText('2020-01-02')).toHaveLength(2)
  expect(screen.getByText(/Coverage and scope do not establish complete account history/)).toBeTruthy()
  expect(screen.queryByRole('heading', { name: 'Saved cash choice needs review' })).toBeNull()
})

it('remembers observed archival across native choices and rejects a contradictory active main amount', async () => {
  await openSelected(); override(routes.snapshots, body => snapshotPage(3, body.before, { account_state: 'archived' }))
  click('Inspect pinned snapshot'); await screen.findByRole('heading', { name: 'Retained cash snapshot revisions' })
  expect(screen.getByText(/This bank account is archived/)).toBeTruthy()
  click('Choose native currency'); await screen.findByRole('heading', { name: 'Inspect a native cash choice' })
  const usdChoice = choice(1, { id: id(21), currency: 'USD', snapshot_id: id(31), snapshot_revision: 1 })
  override(routes.choices, () => ({ items: [choice(), usdChoice], next_after: null }))
  override(routes.resolve, () => selected(usdChoice, snapshot(1, { id: id(31), currency: 'USD', components: cash('98765.43', 'USD') })))
  fireEvent.change(screen.getByLabelText('Native currency'), { target: { value: 'USD' } }); click('View saved cash choice'); await blocked()
})

it.each(['unchanged head', 'newer head'])('refreshes archived retained evidence with %s while preserving the original active pin', async scenario => {
  await openSelected()
  const retainedHead = scenario === 'newer head' ? 4 : 3
  override(routes.snapshots, body => snapshotPage(retainedHead, body.before, { account_state: 'archived' }))
  click('Inspect pinned snapshot'); await screen.findByRole('heading', { name: 'Retained cash snapshot revisions' })
  expect(screen.getByText(/This bank account is archived/)).toBeTruthy()
  expect(screen.getAllByText('INR 12,345.60')).toHaveLength(3)
  click('Refresh snapshot revisions'); await screen.findByRole('heading', { name: 'Snapshot revision 3' })
  expect(screen.getAllByText('INR 12,345.60')).toHaveLength(3)
  click('Latest snapshot revisions'); await screen.findByRole('heading', { name: `Snapshot revision ${retainedHead}` })
  expect(screen.getAllByText('Historical native cash')).toHaveLength(retainedHead)
  click('Pinned snapshot revision'); await screen.findByRole('heading', { name: 'Snapshot revision 3' })
  expect(screen.getByText(/Choice revision 2 pinned snapshot revision 3/)).toBeTruthy()
  expect(screen.getAllByText('INR 12,345.60')).toHaveLength(3)
  expect(screen.getAllByText('2026-10-20T23:45:16.123456+05:30')).toHaveLength(6)
  expect(screen.queryByRole('heading', { name: 'Snapshot revision 4' })).toBeNull()
  expect(bodies(routes.snapshots).map(body => body.before)).toEqual([4, 4, null, 4])
  // A choice advanced to the newer head before archival may resolve as archived;
  // an unchanged choice pinned below that head would correctly resolve as stale.
  const archivedChoice = scenario === 'newer head' ? choice(3, { snapshot_revision: 4 }) : choice()
  override(routes.resolve, () => ({ selection: archivedChoice, state: 'archived', snapshot: null }))
  click('Back to saved cash'); await screen.findByRole('heading', { name: 'Cash choice belongs to an archived account' })
  expect(screen.queryByText('Reported native cash')).toBeNull(); expect(screen.queryByText('Historical native cash')).toBeNull()
  expect(screen.queryByText('INR 12,345.60')).toBeNull()
  override(routes.snapshots, body => snapshotPage(retainedHead, body.before))
  click('Inspect pinned snapshot'); await blocked()
})

it('reads exact pins, latest and earlier snapshot pages separately and retains the pin on return', async () => {
  override(routes.snapshots, body => snapshotPage(30, body.before))
  await openSelected(); click('Inspect pinned snapshot'); await screen.findByRole('heading', { name: 'Snapshot revision 3' })
  expect(screen.queryByRole('heading', { name: 'Snapshot revision 30' })).toBeNull()
  click('Latest snapshot revisions'); await screen.findByRole('heading', { name: 'Snapshot revision 30' })
  expect(screen.queryByRole('heading', { name: 'Snapshot revision 3' })).toBeNull()
  click('Earlier snapshots'); await screen.findByRole('heading', { name: 'Snapshot revision 5' })
  expect(screen.getByRole('heading', { name: 'Snapshot revision 1' })).toBeTruthy()
  expect((screen.getByRole('button', { name: 'Earlier snapshots' }) as HTMLButtonElement).disabled).toBe(true)
  click('Refresh snapshot revisions'); await screen.findByRole('heading', { name: 'Snapshot revision 5' })
  click('Pinned snapshot revision'); await screen.findByRole('heading', { name: 'Snapshot revision 3' })
  expect(bodies(routes.snapshots).map(body => body.before)).toEqual([4, null, 6, 6, 4])
  expect(screen.queryByRole('heading', { name: 'Snapshot revision 30' })).toBeNull()
})

it('retains a choice-history cursor through nested inspection and rereads that exact page', async () => {
  override(routes.history, body => choicePage(30, body.before))
  await openSelected(); click('Choice history'); await screen.findByRole('heading', { name: 'Choice revision 30' })
  click('Earlier choices'); await screen.findByRole('heading', { name: 'Choice revision 5' })
  click('Inspect pinned snapshot for choice revision 4'); await screen.findByRole('heading', { name: 'Retained cash snapshot revisions' })
  click('Back to choice history'); await screen.findByRole('heading', { name: 'Choice revision 5' })
  expect(screen.queryByRole('heading', { name: 'Choice revision 30' })).toBeNull()
  expect(bodies(routes.history).map(body => body.before)).toEqual([null, 6, 6])
  click('Latest choice revisions'); await screen.findByRole('heading', { name: 'Choice revision 30' })
  expect(screen.queryByRole('heading', { name: 'Choice revision 5' })).toBeNull()
})

it('allows a corrected choice to switch from snapshot root A revision 10 to root B revision 1', async () => {
  const original = choice(2, { snapshot_revision: 10 }), corrected = choice(3, { snapshot_id: id(31), snapshot_revision: 1 })
  override(routes.choices, () => ({ items: [original], next_after: null }))
  override(routes.resolve, () => selected(original, snapshot(10)))
  await openSelected()
  override(routes.resolve, () => selected(corrected, snapshot(1, { id: id(31), components: cash('77.00') })))
  click('Refresh saved choice'); await screen.findByText('INR 77.00')
  expect(screen.getByText(/Showing choice revision 3/)).toBeTruthy(); expect(screen.queryByText('INR 12,345.60')).toBeNull()
  override(routes.snapshots, body => snapshotPage(1, body.before, { id: id(31), components: cash('77.00') }))
  click('Inspect pinned snapshot'); await screen.findByRole('heading', { name: 'Snapshot revision 1' })
  expect(bodies(routes.snapshots)).toEqual([{ id: id(31), limit: 25, before: 2 }])
})

it.each(['regressed revision', 'changed equal-head target'])('rejects a %s after observing a newer choice in retained history', async failure => {
  await openSelected(); override(routes.history, body => choicePage(3, body.before))
  click('Choice history'); await screen.findByRole('heading', { name: 'Choice revision 3' })
  override(routes.resolve, () => failure === 'regressed revision' ? selected() : selected(choice(3, { snapshot_id: id(31) }), snapshot(3, { id: id(31) })))
  click('Back to saved cash'); await blocked()
})

it.each(['regressed head', 'changed equal-head amount', 'changed original pin'])('rejects %s after viewing a newer snapshot head', async failure => {
  await openSelected(); override(routes.snapshots, body => snapshotPage(5, body.before))
  click('Inspect pinned snapshot'); await screen.findByRole('heading', { name: 'Snapshot revision 3' })
  click('Latest snapshot revisions'); await screen.findByRole('heading', { name: 'Snapshot revision 5' })
  override(routes.snapshots, body => {
    const page = snapshotPage(failure === 'regressed head' ? 4 : 5, body.before)
    return { ...page, items: page.items.map(item => item.revision === (failure === 'changed original pin' ? 3 : 5) ? { ...item, components: cash('98765.43') } : item) }
  })
  click(failure === 'changed original pin' ? 'Pinned snapshot revision' : 'Refresh snapshot revisions'); await blocked()
})

it.each(['second-currency position', 'undeclared currency', 'duplicate scope', 'unproven continuation'])('rejects %s across the whole discovery response before resolving a matching first row', async failure => {
  override(routes.choices, () => ({ items: failure === 'unproven continuation' ? [choice()] : [choice(), choice(1, { id: id(21), currency: failure === 'duplicate scope' ? 'INR' : failure === 'undeclared currency' ? 'EUR' : 'USD', ...(failure === 'second-currency position' ? { position_id: id(60) } : {}) })], next_after: failure === 'unproven continuation' ? id(20) : null }))
  await openCash(); fireEvent.change(screen.getByLabelText('Native currency'), { target: { value: 'INR' } }); click('View saved cash choice'); await blocked()
  expect(calls(routes.resolve)).toHaveLength(0)
})

it.each(['snapshot account', 'snapshot native currency', 'missing cash', 'invalid calendar day', 'extra response field', 'nonselected amount', 'equal-head changed source'])('validates %s inside the protected resolve response and clears previous values', async failure => {
  await openSelected()
  override(routes.resolve, () => {
    if (failure === 'extra response field') return { ...selected(), extra: 'private evidence' }
    if (failure === 'nonselected amount') return { ...selected(), state: 'stale' }
    const changes = failure === 'snapshot account' ? { account_id: id(999) } : failure === 'snapshot native currency' ? { currency: 'USD', components: cash('98765.43', 'USD') } : failure === 'missing cash' ? { components: [{ role: 'net_cash', source: null, currency: 'INR', missing_reason: 'not_supplied' }] } : failure === 'invalid calendar day' ? { as_of_date: '2026-02-30', as_of_instant: null } : { source_row_id: id(999) }
    return selected(choice(), snapshot(3, changes))
  })
  click('Refresh saved choice'); await blocked()
})

it.each(['wrong pin', 'gap', 'truncated history', 'foreign older currency'])('rejects %s in snapshot history before showing any historical amount', async failure => {
  await openSelected()
  override(routes.snapshots, () => {
    const page = snapshotPage(failure === 'wrong pin' ? 2 : 3)
    if (failure === 'gap') return { items: [page.items[0], page.items[2]], next_before: null }
    if (failure === 'truncated history') return { items: [page.items[0]], next_before: null }
    return { ...page, items: page.items.map(item => failure === 'foreign older currency' && item.revision === 1 ? { ...item, currency: 'USD', components: cash('98765.43', 'USD') } : item) }
  })
  click('Inspect pinned snapshot'); await blocked()
})

it.each(['light', 'dark'])('masks selected and historical native amounts in %s mode without browser storage', async appearance => {
  theme = appearance; masked = true
  const storage = vi.spyOn(Storage.prototype, 'setItem')
  await openSelected(); expect(document.documentElement.dataset.theme).toBe(appearance)
  expect(screen.getByText('••••')).toBeTruthy(); expect(document.querySelector('.wb-cash')!.innerHTML).not.toMatch(/12345\.60|12,345\.60/)
  expect(screen.getAllByText('2026-10-20T23:45:16.123456+05:30')).toHaveLength(2)
  click('Inspect pinned snapshot'); await screen.findByRole('heading', { name: 'Retained cash snapshot revisions' })
  const view = document.querySelector('.wb-cash')!
  expect(screen.getAllByText('••••')).toHaveLength(3); expect(view.innerHTML).not.toMatch(/12345\.60|12,345\.60/)
  expect(screen.getAllByText('2026-10-20T23:45:16.123456+05:30')).toHaveLength(6)
  expect(storage).not.toHaveBeenCalled(); expect(localStorage.length).toBe(0); expect(sessionStorage.length).toBe(0)
  expect((await axe.run(view, { rules: { 'color-contrast': { enabled: false }, region: { enabled: false } } })).violations).toEqual([])
  storage.mockRestore()
})

it('keeps exact native INR and USD under display preference changes and applies masking without rereads', async () => {
  await openSelected(); const count = calls().length
  fireEvent.change(screen.getByLabelText('Display currency'), { target: { value: 'USD' } }); click('Save preferences')
  await screen.findByText(/Your USD display preference does not convert these native values/)
  expect(screen.getByText('INR 12,345.60')).toBeTruthy(); expect(calls()).toHaveLength(count)
  fireEvent.change(screen.getByLabelText('Amount privacy'), { target: { value: 'hidden' } }); click('Save preferences'); await screen.findByText('••••')
  expect(screen.queryByText('INR 12,345.60')).toBeNull(); expect(calls()).toHaveLength(count)
  fireEvent.change(screen.getByLabelText('Amount privacy'), { target: { value: 'visible' } }); click('Save preferences'); await screen.findByText('INR 12,345.60')
  click('Choose native currency'); await screen.findByRole('heading', { name: 'Inspect a native cash choice' })
  expect(screen.queryByText('INR 12,345.60')).toBeNull()
  const usdChoice = choice(1, { id: id(21), currency: 'USD', snapshot_id: id(31), snapshot_revision: 1 })
  override(routes.choices, () => ({ items: [choice(), usdChoice], next_after: null }))
  override(routes.resolve, () => selected(usdChoice, snapshot(1, { id: id(31), currency: 'USD', components: cash('9007199254740991.01', 'USD') })))
  await submit('USD'); expect(screen.getByText('USD 9,007,199,254,740,991.01')).toBeTruthy()
})

it.each(['snapshot read', 'nested history return', 'resolved return'])('clears account context after a %s failure and recovers through a fresh directory', async failure => {
  await openSelected(); click('Choice history'); await screen.findByRole('heading', { name: 'Cash choice history' })
  if (failure === 'snapshot read') { override(routes.snapshots, () => ({ detail: 'private source payload' }), 409); click('Inspect pinned snapshot for choice revision 2') }
  else {
    click('Inspect pinned snapshot for choice revision 2'); await screen.findByRole('heading', { name: 'Retained cash snapshot revisions' })
    if (failure === 'nested history return') { override(routes.history, () => ({ detail: 'private source payload' }), 409); click('Back to choice history') }
    else { click('Back to choice history'); await screen.findByRole('heading', { name: 'Cash choice history' }); override(routes.resolve, () => ({ detail: 'private source payload' }), 409); click('Back to saved cash') }
  }
  await screen.findByText('Bank evidence could not be verified.')
  expect(document.querySelector('.wb-cash')).toBeNull(); expect(screen.queryByText('HDFC · Everyday account')).toBeNull()
  expect(document.body.textContent).not.toMatch(/private source payload|12,345/)
  const previousReads = calls(routes.accounts).length
  click('Reload saved bank accounts'); await screen.findByRole('heading', { name: 'Saved bank accounts on this page' })
  expect(calls(routes.accounts)).toHaveLength(previousReads + 1)
  click('View saved cash for HDFC Everyday account'); await screen.findByRole('heading', { name: 'Inspect a native cash choice' })
  expect((screen.getByLabelText('Native currency') as HTMLSelectElement).value).toBe('')
})

it.each(['navigate', 'unmount', 'lock', 'logout', 'session'])('discards a late snapshot response after %s', async action => {
  const mounted = await openSelected(), finish = defer(routes.snapshots)
  click('Inspect pinned snapshot'); await screen.findByRole('heading', { name: 'Checking saved cash evidence…' })
  expect(screen.queryByText('INR 12,345.60')).toBeNull()
  if (action === 'navigate') fireEvent.click(within(screen.getByRole('navigation', { name: 'Workspace navigation' })).getByRole('button', { name: 'Overview' }))
  else if (action === 'unmount') mounted.unmount()
  else if (action === 'logout') click('Sign out here')
  else if (action === 'session') {
    const previous = fetchMock.getMockImplementation()!
    fetchMock.mockImplementation((path, options) => path === '/api/v1/auth/session' ? Promise.resolve(response({ ...session(), workspace_context: 'e'.repeat(64) })) : previous(path, options))
    await act(async () => { auth.suspend(); await auth.bootstrap() })
  } else await act(async () => auth.lock())
  await act(async () => finish(snapshotPage()))
  expect(document.querySelector('.wb-cash')).toBeNull(); expect(document.body.innerHTML).not.toMatch(/12,345|12345/)
})

it.each([
  ['choice discovery', routes.choices], ['choice resolution', routes.resolve],
  ['choice history', routes.history], ['snapshot history', routes.snapshots],
] as const)('ignores a malformed late %s payload after navigating to Overview', async (operation, route) => {
  if (operation === 'choice discovery' || operation === 'choice resolution') await openCash()
  else await openSelected()
  const previousReads = calls(route).length, finish = defer(route)
  if (operation === 'choice discovery' || operation === 'choice resolution') {
    fireEvent.change(screen.getByLabelText('Native currency'), { target: { value: 'INR' } }); click('View saved cash choice')
  } else click(operation === 'choice history' ? 'Choice history' : 'Inspect pinned snapshot')
  await waitFor(() => expect(calls(route)).toHaveLength(previousReads + 1))
  await screen.findByRole('heading', { name: 'Checking saved cash evidence…' })
  fireEvent.click(within(screen.getByRole('navigation', { name: 'Workspace navigation' })).getByRole('button', { name: 'Overview' }))
  await screen.findByRole('heading', { name: 'A fresh start.' })
  await act(async () => finish({ invalid: 'late private payload', amount: '98765.43' }))
  expect(auth.snapshot().screen).toMatchObject({ kind: 'workspace' })
  expect(screen.getByRole('heading', { name: 'A fresh start.' })).toBeTruthy()
  expect(screen.queryByRole('heading', { name: 'Unable to verify this response.' })).toBeNull()
  expect(document.querySelector('.wb-cash')).toBeNull()
  expect(document.body.innerHTML).not.toMatch(/12,345|12345|98,765|98765|late private payload/)
  expect(calls(route)).toHaveLength(previousReads + 1)
})

it('clears displayed selected cash when a session check detects a different workspace', async () => {
  await openSelected(); const previous = fetchMock.getMockImplementation()!
  fetchMock.mockImplementation((path, options) => path === '/api/v1/auth/session' ? Promise.resolve(response({ ...session(), workspace_context: 'e'.repeat(64) })) : previous(path, options))
  await act(async () => auth.check())
  expect(auth.snapshot().screen).toMatchObject({ kind: 'blocked', reason: 'context' }); expect(document.querySelector('.wb-cash')).toBeNull()
})

it('supports keyboard selection and historical inspection with protected read-only requests', async () => {
  await openBanking(); const user = userEvent.setup()
  const enter = async (name: string) => {
    const button = screen.getByRole('button', { name })
    await waitFor(() => expect((button as HTMLButtonElement).disabled).toBe(false))
    button.focus(); expect(document.activeElement).toBe(button); await user.keyboard('{Enter}')
  }
  const focused = async (name: string) => { const heading = await screen.findByRole('heading', { name }); expect(document.activeElement).toBe(heading) }
  await enter('View saved cash for HDFC Everyday account')
  await focused('Inspect a native cash choice')
  await user.selectOptions(screen.getByLabelText('Native currency'), 'INR')
  await enter('View saved cash choice'); await focused('Selected cash snapshot')
  await enter('Choice history'); await focused('Cash choice history')
  await enter('Inspect pinned snapshot for choice revision 1'); await focused('Retained cash snapshot revisions')
  await user.click(screen.getByText('Snapshot provenance · revision 3'))
  expect(screen.getByText('Snapshot provenance · revision 3').closest('details')!.open).toBe(true)
  expect(calls().every(([path]) => Object.values(routes).includes(String(path) as typeof routes[keyof typeof routes]))).toBe(true)
  for (const [path, options] of calls()) {
    expect(String(path)).not.toContain('?')
    expect(options).toMatchObject({ method: 'POST', credentials: 'same-origin', cache: 'no-store', redirect: 'error' })
    const headers = new Headers(options!.headers)
    expect(headers.get('X-CSRFToken')).toBe('synthetic-csrf-value-long-enough')
  }
  expect(localStorage.length).toBe(0); expect(sessionStorage.length).toBe(0)
})
