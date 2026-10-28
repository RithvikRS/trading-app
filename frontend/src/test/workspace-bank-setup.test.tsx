import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import axe from 'axe-core'
import Workspace from '../../workspace/src/Workspace'
import { AuthController } from '../../workspace/src/auth'
import { bankSetupCommand, bankSetupInput, parseBankSetupReceipt, parseBankSetupSnapshot } from '../../workspace/src/bank-setup'
import type { BankSetupCommand, BankSetupReceipt } from '../../workspace/src/bank-setup'
import type { Account } from '../../workspace/src/accounts'

const id = (n: number) => `ba000000-0000-4000-8000-${String(n).padStart(12, '0')}`
const input = () => ({ institution: 'hdfc' as const, label: 'Everyday account', currencies: ['INR'] as const })
const command = (n = 1, revision = 0) => bankSetupCommand(id(n), revision, input())
const receipt = (n = 1, revision = 1): BankSetupReceipt => ({ intent_id: id(n), revision, account_id: id(n + 1000), ...input() })
const session = (context = 'b'.repeat(64)) => ({ status: 'authenticated', workspace_context: context, expires_at: new Date(Date.now() + 28_800_000).toISOString(), idle_expires_at: new Date(Date.now() + 900_000).toISOString(), fresh_until: new Date(Date.now() + 300_000).toISOString(), factors: [id(99)], unverified_factors: [] })
const response = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store', Date: new Date().toUTCString() } })
const fetchMock = vi.fn<typeof fetch>()
let auth: AuthController, head: number, lastSaved: BankSetupReceipt | null, accounts: Account[], saved: Map<string, BankSetupReceipt>, theme: string, display: string, random: number
const setupCalls = () => fetchMock.mock.calls.filter(([path]) => String(path).startsWith('/api/v1/finance/bank-account-setup/'))
const creates = () => setupCalls().filter(([path]) => String(path).endsWith('/create'))
const queries = () => setupCalls().filter(([path]) => String(path).endsWith('/query'))
function commit(body: BankSetupCommand): BankSetupReceipt {
  const original = saved.get(body.intent_id)
  if (original) return original
  const result: BankSetupReceipt = { intent_id: body.intent_id, revision: ++head, account_id: id(head + 1000), institution: body.institution, label: body.label, currencies: [...body.currencies] }
  saved.set(body.intent_id, result); lastSaved = result
  accounts.push({ id: result.account_id, kind: 'bank', institution: result.institution, market: 'IN', label: result.label, currencies: [...result.currencies], revision: 1, state: 'active' })
  return result
}
function override(path: string, handler: (body: BankSetupCommand) => Response | Promise<Response>) {
  const previous = fetchMock.getMockImplementation()!
  fetchMock.mockImplementation((url, options) => url === '/api/v1/finance/' + path ? Promise.resolve(handler(JSON.parse(String(options?.body ?? '{}')))) : previous(url, options))
}
beforeEach(() => {
  head = 0; lastSaved = null; accounts = []; saved = new Map(); theme = 'light'; display = 'INR'; random = 100
  document.cookie = 'trading_dev_csrf=synthetic-csrf-value-long-enough; Path=/'
  vi.spyOn(crypto, 'randomUUID').mockImplementation(() => id(random++) as ReturnType<Crypto['randomUUID']>)
  vi.stubGlobal('fetch', fetchMock); fetchMock.mockReset(); auth = new AuthController()
  fetchMock.mockImplementation(async (path, options) => {
    if (path === '/api/v1/auth/bootstrap') return response({ status: 'ready', recovery_email_enabled: false })
    if (path === '/api/v1/auth/session') return response(session())
    if (path === '/api/v1/auth/logout') return response({ status: 'signed_out', provider_cleanup: 'complete' })
    if (path === '/api/v1/preferences') return response({ theme, display_currency: display, amount_masked: true, revision: 1 })
    if (path === '/api/v1/finance/accounts/query') return response({ items: accounts, next_after: null })
    if (path === '/api/v1/finance/bank-account-setup/query') return response({ revision: head, last_saved: lastSaved })
    if (path === '/api/v1/finance/bank-account-setup/create') {
      const body = JSON.parse(String(options?.body)) as BankSetupCommand
      if (!saved.has(body.intent_id) && body.expected_revision !== head) return response({ private: 'conflict detail' }, 409)
      return response(commit(body))
    }
    return response({}, 404)
  })
})
afterEach(() => { auth.lock(); vi.useRealTimers(); vi.unstubAllGlobals(); document.cookie = 'trading_dev_csrf=; Max-Age=0; Path=/'; delete document.documentElement.dataset.theme })
async function openDirectory() {
  const user = userEvent.setup(), result = render(<Workspace controller={auth} />)
  await screen.findByRole('heading', { name: 'A fresh start.' })
  await user.click(within(screen.getByRole('navigation', { name: 'Workspace navigation' })).getByRole('button', { name: 'Accounts' }))
  await waitFor(() => expect((screen.getByRole('button', { name: 'Add bank account' }) as HTMLButtonElement).disabled).toBe(false))
  return { user, ...result }
}
async function openForm() {
  const result = await openDirectory()
  await result.user.click(screen.getByRole('button', { name: 'Add bank account' }))
  await confirmDirectoryReview()
  await screen.findByLabelText('Account name')
  return result
}
async function confirmDirectoryReview() {
  await screen.findByRole('heading', { name: 'Review your saved accounts.' })
  fireEvent.click(screen.getByRole('checkbox', { name: 'I have reviewed the saved directory and intend to create a new account.' }))
  fireEvent.click(screen.getByRole('button', { name: 'Start a new bank account' }))
}
function fill(label = 'Everyday account') {
  fireEvent.change(screen.getByLabelText('Account name'), { target: { value: label } })
  fireEvent.click(screen.getByRole('checkbox', { name: 'INR' }))
}
async function create(label = 'Everyday account') {
  fill(label); fireEvent.click(screen.getByRole('button', { name: 'Create bank account' }))
  await screen.findByRole('heading', { name: 'Creation confirmed.' })
  await waitFor(() => expect(auth.snapshot().busy).toBe(false))
}

it('parses exact immutable bounded setup snapshots, receipts and commands', () => {
  expect(parseBankSetupSnapshot({ revision: 0, last_saved: null })).toEqual({ revision: 0, last_saved: null })
  expect(parseBankSetupSnapshot({ revision: 1000, last_saved: receipt(1, 1000) }).last_saved?.revision).toBe(1000)
  const frozen = command(), parsed = parseBankSetupReceipt(receipt(), frozen)
  expect(Object.isFrozen(frozen)).toBe(true); expect(Object.isFrozen(frozen.currencies)).toBe(true)
  expect(Object.isFrozen(parsed)).toBe(true); expect(Object.isFrozen(parsed.currencies)).toBe(true)
  expect(() => (frozen.currencies as string[]).push('USD')).toThrow()
  expect(parseBankSetupReceipt(receipt())).toEqual(receipt())
})
it.each([
  { revision: -1, last_saved: null }, { revision: 0.5, last_saved: null }, { revision: 1001, last_saved: receipt(1, 1001) },
  { revision: 0, last_saved: receipt() }, { revision: 1, last_saved: null }, { revision: 2, last_saved: receipt() },
  { revision: 0, last_saved: null, owner_id: id(4) }, { revision: 0 },
])('rejects a malformed or inconsistent whole snapshot %#', value => expect(() => parseBankSetupSnapshot(value)).toThrow())
it.each([
  { intent_id: id(1).toUpperCase() }, { account_id: '00000000-0000-0000-0000-000000000000' }, { intent_id: ' ' + id(1) }, { account_id: id(2) + '\n' },
  { revision: 0 }, { revision: 1001 }, { revision: 1.5 }, { institution: 'ubs' }, { label: 'Account 1234' }, { label: 'Name\n' },
  { currencies: ['USD', 'INR'] }, { currencies: ['INR', 'INR'] }, { currencies: [] }, { currencies: ['EUR'] },
  { balance: '0.00' }, { state: 'active' }, { account_id: undefined },
])('rejects malformed, sensitive or extra receipt fields %#', changes => expect(() => parseBankSetupReceipt({ ...receipt(), ...changes })).toThrow())
it.each([
  { intent_id: id(2) }, { revision: 2 }, { institution: 'sbi' }, { label: 'Another account' }, { currencies: ['USD'] },
])('binds the complete creation response to the exact frozen request %#', changes => expect(() => parseBankSetupReceipt({ ...receipt(), ...changes }, command())).toThrow())
it.each(['', ' Leading', '123 Account', 'Name\n', 'Name\r', 'Name\u2028', 'Name\u2029', 'Name\u0000', '<script>', 'Name@example', 'A'.repeat(65), 'Café'])('rejects an unsafe account name %j', label => expect(() => bankSetupInput({ ...input(), label })).toThrow())
it('accepts exactly the three native-currency choices and retains the chosen safe name', () => {
  for (const currencies of [['INR'], ['USD'], ['INR', 'USD']]) expect(bankSetupInput({ ...input(), label: 'Savings (Family) - Main.', currencies }).currencies).toEqual(currencies)
  expect(() => bankSetupCommand('00000000-0000-0000-0000-000000000000', 0, input())).toThrow()
  expect(() => bankSetupCommand(id(1), 1001, input())).toThrow()
})
it('uses protected finance POST reads only after explicit entry', async () => {
  await auth.finance('/bank-account-setup/query', {}, parseBankSetupSnapshot); expect(fetchMock).not.toHaveBeenCalled()
  await openDirectory(); expect(setupCalls()).toHaveLength(0)
  fireEvent.click(screen.getByRole('button', { name: 'Add bank account' })); await screen.findByRole('heading', { name: 'Review your saved accounts.' })
  expect(queries()).toHaveLength(1); expect(creates()).toHaveLength(0)
  expect(queries()[0]).toEqual(['/api/v1/finance/bank-account-setup/query', expect.objectContaining({ method: 'POST', body: '{}', credentials: 'same-origin', mode: 'same-origin', redirect: 'error', cache: 'no-store', referrerPolicy: 'no-referrer', headers: expect.objectContaining({ 'X-CSRFToken': 'synthetic-csrf-value-long-enough', 'X-Workspace-Context': 'b'.repeat(64) }) })])
})
it('validates before querying or allocating an intent and keeps currencies independent of display preference', async () => {
  display = 'USD'; await openForm()
  expect((screen.getByRole('checkbox', { name: 'USD' }) as HTMLInputElement).checked).toBe(false)
  fireEvent.click(screen.getByRole('button', { name: 'Create bank account' })); await screen.findByRole('alert')
  expect(queries()).toHaveLength(2); expect(crypto.randomUUID).not.toHaveBeenCalled(); expect(creates()).toHaveLength(0)
  fill('Account 1234'); expect(screen.queryByRole('alert')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'Create bank account' })); expect(screen.getByRole('alert')).toBeTruthy(); expect(creates()).toHaveLength(0)
  fireEvent.change(screen.getByLabelText('Account name'), { target: { value: 'Personal savings' } })
  expect(screen.queryByRole('alert')).toBeNull()
  fireEvent.change(screen.getByLabelText('Institution'), { target: { value: 'sbi' } })
  fireEvent.click(screen.getByRole('button', { name: 'Create bank account' })); await screen.findByRole('heading', { name: 'Creation confirmed.' })
  expect(JSON.parse(String(creates()[0]![1]!.body))).toMatchObject({ institution: 'sbi', label: 'Personal savings', currencies: ['INR'], expected_revision: 0 })
})
it('creates once, shows a historical receipt and refreshes the persisted directory', async () => {
  await openForm(); await create()
  expect(queries()).toHaveLength(3); expect(creates()).toHaveLength(1); expect(crypto.randomUUID).toHaveBeenCalledTimes(1)
  expect(await within(screen.getByRole('list', { name: 'Saved accounts' })).findByText('Everyday account')).toBeTruthy()
  const creation = screen.getByRole('complementary', { name: 'Original creation receipt' })
  expect(within(creation).getByText(/historical creation/)).toBeTruthy(); expect(creation.textContent).not.toMatch(/Connected|₹|\$0/)
  expect(fetchMock.mock.calls.at(-1)?.[0]).toBe('/api/v1/finance/accounts/query')
})
it('blocks synchronous double submission and freezes the selected payload before the query returns', async () => {
  await openForm(); fill()
  let finish!: (value: Response) => void
  override('bank-account-setup/query', () => new Promise(resolve => { finish = resolve }))
  const name = screen.getByLabelText('Account name'), form = screen.getByRole('button', { name: 'Create bank account' }).closest('form')!
  act(() => { fireEvent.submit(form); fireEvent.submit(form); fireEvent.change(name, { target: { value: 'Changed later' } }) })
  expect(queries()).toHaveLength(3); expect(creates()).toHaveLength(0)
  await act(async () => finish(response({ revision: 0, last_saved: null })))
  await screen.findByRole('heading', { name: 'Creation confirmed.' })
  expect(creates()).toHaveLength(1); expect(crypto.randomUUID).toHaveBeenCalledTimes(1)
  expect(JSON.parse(String(creates()[0]![1]!.body)).label).toBe('Everyday account')
})
it('retries a lost successful response with the exact original key, head and payload after another tab advances', async () => {
  let lost = true
  override('bank-account-setup/create', async body => { const result = commit(body); if (lost) { lost = false; throw new TypeError('lost response') } return response(result) })
  await openForm(); fill(); fireEvent.click(screen.getByRole('button', { name: 'Create bank account' }))
  await screen.findByRole('heading', { name: 'The save is not confirmed.' }); expect(accounts).toHaveLength(1)
  commit(bankSetupCommand(id(500), head, { ...input(), label: 'Other tab account' })); expect(head).toBe(2)
  const before = queries().length
  fireEvent.click(screen.getByRole('button', { name: 'Retry the same save' })); await screen.findByRole('heading', { name: 'Creation confirmed.' })
  await waitFor(() => expect(auth.snapshot().busy).toBe(false))
  expect(queries()).toHaveLength(before); expect(creates()).toHaveLength(2); expect(creates()[1]![1]!.body).toBe(creates()[0]![1]!.body)
  expect(crypto.randomUUID).toHaveBeenCalledTimes(1); expect(accounts).toHaveLength(2)
  expect(within(screen.getByRole('complementary', { name: 'Original creation receipt' })).getByText(/Creation revision 1/)).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: 'Review directory before another account' })); await screen.findByRole('heading', { name: 'Review your saved accounts.' })
  expect(screen.getByText(/does not prove an older unconfirmed request failed/)).toBeTruthy()
  fireEvent.click(screen.getByRole('checkbox', { name: /I have reviewed/ })); fireEvent.click(screen.getByRole('button', { name: 'Start a new bank account' }))
  await screen.findByLabelText('Account name'); await create('Intended next account')
  expect(JSON.parse(String(creates().at(-1)![1]!.body))).toMatchObject({ expected_revision: 2, label: 'Intended next account' })
  expect(crypto.randomUUID).toHaveBeenCalledTimes(2)
})
it.each([429, 503])('keeps an explicit exact retry after unavailable creation HTTP %s', async status => {
  override('bank-account-setup/create', () => response({ private: 'private failure body' }, status))
  await openForm(); fill(); fireEvent.click(screen.getByRole('button', { name: 'Create bank account' }))
  await screen.findByRole('heading', { name: 'The save is not confirmed.' })
  expect(creates()).toHaveLength(1); expect(document.body.textContent).not.toContain('private failure body')
  fireEvent.click(screen.getByRole('button', { name: 'Retry the same save' })); await screen.findByRole('heading', { name: 'The save is not confirmed.' })
  expect(creates()[1]![1]!.body).toBe(creates()[0]![1]!.body); expect(crypto.randomUUID).toHaveBeenCalledTimes(1)
})
it('requires directory review if the head changed before submission, without allocating or sending a creation', async () => {
  await openForm(); commit(bankSetupCommand(id(500), 0, { ...input(), label: 'Other tab account' }))
  fill(); fireEvent.click(screen.getByRole('button', { name: 'Create bank account' })); await screen.findByRole('heading', { name: 'Review your saved accounts.' })
  expect(creates()).toHaveLength(0); expect(crypto.randomUUID).not.toHaveBeenCalled()
  expect((screen.getByRole('button', { name: 'Start a new bank account' }) as HTMLButtonElement).disabled).toBe(true)
  expect(within(screen.getByRole('list', { name: 'Saved accounts' })).getByText('Other tab account')).toBeTruthy()
  fireEvent.click(screen.getByRole('checkbox', { name: /I have reviewed/ })); fireEvent.click(screen.getByRole('button', { name: 'Start a new bank account' }))
  await screen.findByLabelText('Account name'); await create('Another intended account')
  expect(JSON.parse(String(creates()[0]![1]!.body)).expected_revision).toBe(1)
})
it('clears a conflicting command and cannot bypass directory review by closing and reopening setup', async () => {
  override('bank-account-setup/create', () => response({}, 409))
  await openForm(); fill(); fireEvent.click(screen.getByRole('button', { name: 'Create bank account' })); await screen.findByRole('heading', { name: 'Review your saved accounts.' })
  expect(screen.queryByRole('button', { name: 'Retry the same save' })).toBeNull(); expect(creates()).toHaveLength(1)
  fireEvent.click(screen.getByRole('button', { name: 'Close setup' })); fireEvent.click(screen.getByRole('button', { name: 'Add bank account' }))
  await screen.findByRole('heading', { name: 'Review your saved accounts.' })
  expect(screen.queryByLabelText('Account name')).toBeNull(); expect(creates()).toHaveLength(1)
})
it('requires a successful directory refresh before allowing a reviewed new intent', async () => {
  override('bank-account-setup/create', () => response({}, 409))
  await openForm(); override('accounts/query', () => response({}, 503)); fill(); fireEvent.click(screen.getByRole('button', { name: 'Create bank account' }))
  await screen.findByRole('button', { name: 'Reload directory for review' })
  expect(screen.queryByRole('button', { name: 'Start a new bank account' })).toBeNull(); expect(creates()).toHaveLength(1)
})
it('keeps creation confirmation when the saved account falls beyond the displayed page', async () => {
  const firstPage: Account[] = Array.from({ length: 25 }, (_, n) => ({ id: id(n + 1), kind: 'bank', institution: 'hdfc', market: 'IN', label: 'Existing account', currencies: ['INR'], revision: 1, state: 'active' }))
  override('accounts/query', () => response({ items: firstPage, next_after: id(25) }))
  await openForm(); await create('Account on a later page')
  expect(within(screen.getByRole('complementary', { name: 'Original creation receipt' })).getByText('HDFC · Account on a later page')).toBeTruthy()
  expect(within(screen.getByRole('list', { name: 'Saved accounts' })).queryByText('Account on a later page')).toBeNull()
  expect(screen.getByText(/account is on a later page/)).toBeTruthy(); expect(screen.queryByText(/account was not saved|account is missing/i)).toBeNull()
})
it('shows a full setup limit without creating or allocating a key', async () => {
  head = 1000; lastSaved = receipt(1, 1000); await openDirectory()
  fireEvent.click(screen.getByRole('button', { name: 'Add bank account' })); await confirmDirectoryReview(); await screen.findByText(/setup limit has been reached/)
  expect(screen.getByText(/setup limit has been reached/)).toBeTruthy(); expect(screen.queryByRole('button', { name: 'Create bank account' })).toBeNull()
  expect(creates()).toHaveLength(0); expect(crypto.randomUUID).not.toHaveBeenCalled()
})
it.each([401, 403, 412, 'invalid'] as const)('uses the global boundary and clears private setup on creation failure %s', async failure => {
  override('bank-account-setup/create', body => failure === 'invalid' ? response({ ...commit(body), balance: 'private response' }) : response({ private: 'private response' }, failure))
  await openForm(); fill(); fireEvent.click(screen.getByRole('button', { name: 'Create bank account' }))
  await waitFor(() => expect(auth.snapshot().screen.kind).not.toBe('workspace'))
  expect(document.querySelector('.bs-setup')).toBeNull(); expect(document.body.textContent).not.toMatch(/Everyday account|private response/)
  expect(creates()).toHaveLength(1)
})
it('rejects an inconsistent query through the protocol boundary before exposing a form', async () => {
  override('bank-account-setup/query', () => response({ revision: 2, last_saved: receipt() }))
  await openDirectory(); fireEvent.click(screen.getByRole('button', { name: 'Add bank account' }))
  await screen.findByRole('heading', { name: 'Unable to verify this response.' })
  expect(creates()).toHaveLength(0); expect(document.querySelector('.bs-setup')).toBeNull()
})
it.each(['navigate', 'lock', 'session'] as const)('discards a late create result after %s and never automatically resubmits it', async action => {
  let finish!: (value: Response) => void, pending!: BankSetupCommand
  override('bank-account-setup/create', body => { pending = body; return new Promise(resolve => { finish = resolve }) })
  await openForm(); fill(); fireEvent.click(screen.getByRole('button', { name: 'Create bank account' })); await screen.findByText('Saving account details…')
  if (action === 'navigate') fireEvent.click(within(screen.getByRole('navigation', { name: 'Workspace navigation' })).getByRole('button', { name: 'Overview' }))
  else if (action === 'lock') await act(async () => auth.lock())
  else await act(async () => { auth.suspend(); await auth.bootstrap() })
  await act(async () => finish(response(commit(pending))))
  expect(document.querySelector('.bs-panel')).toBeNull(); expect(document.body.textContent).not.toContain('Creation confirmed.')
  expect(creates()).toHaveLength(1)
  if (action !== 'lock') {
    fireEvent.click(within(screen.getByRole('navigation', { name: 'Workspace navigation' })).getByRole('button', { name: 'Accounts' }))
    await screen.findByRole('button', { name: 'Add bank account' }); expect(document.querySelector('.bs-panel')).toBeNull(); expect(creates()).toHaveLength(1)
  }
})
it('does not create after navigation while the pre-submit head query is pending', async () => {
  await openForm(); fill(); let finish!: (value: Response) => void
  override('bank-account-setup/query', () => new Promise(resolve => { finish = resolve }))
  fireEvent.click(screen.getByRole('button', { name: 'Create bank account' })); await screen.findByText('Checking the saved revision before creating…')
  fireEvent.click(within(screen.getByRole('navigation', { name: 'Workspace navigation' })).getByRole('button', { name: 'Overview' }))
  await act(async () => finish(response({ revision: 0, last_saved: null })))
  expect(creates()).toHaveLength(0); expect(crypto.randomUUID).not.toHaveBeenCalled(); expect(document.querySelector('.bs-panel')).toBeNull()
})
it('clears a frozen uncertain request when an idle check detects a replaced owner context', async () => {
  override('bank-account-setup/create', () => response({}, 503))
  await openForm(); fill(); fireEvent.click(screen.getByRole('button', { name: 'Create bank account' })); await screen.findByRole('heading', { name: 'The save is not confirmed.' })
  const previous = fetchMock.getMockImplementation()!
  fetchMock.mockImplementation((path, options) => path === '/api/v1/auth/session' ? Promise.resolve(response(session('c'.repeat(64)))) : previous(path, options))
  await act(async () => auth.check()); expect(auth.snapshot().screen).toMatchObject({ kind: 'blocked', reason: 'context' })
  expect(document.body.textContent).not.toContain('Everyday account'); expect(creates()).toHaveLength(1)
})
it('discards an uncertain save on page suspension and does not restore or resubmit it after re-entry', async () => {
  override('bank-account-setup/create', () => response({}, 503))
  await openForm(); fill(); fireEvent.click(screen.getByRole('button', { name: 'Create bank account' })); await screen.findByRole('heading', { name: 'The save is not confirmed.' })
  fireEvent(window, new Event('pagehide')); expect(document.querySelector('.bs-panel')).toBeNull()
  fireEvent(window, new Event('pageshow')); await screen.findByRole('heading', { name: 'A fresh start.' })
  expect(creates()).toHaveLength(1); expect(document.body.textContent).not.toContain('Everyday account')
})
it.each(['light', 'dark'])('supports keyboard focus and accessible setup without browser storage in %s mode', async mode => {
  theme = mode; const storage = vi.spyOn(Storage.prototype, 'setItem'), readStorage = vi.spyOn(Storage.prototype, 'getItem')
  const { user, container } = await openDirectory()
  screen.getByRole('button', { name: 'Add bank account' }).focus(); await user.keyboard('{Enter}')
  await screen.findByRole('heading', { name: 'Review your saved accounts.' })
  expect(document.activeElement).toBe(screen.getByRole('heading', { name: 'Review your saved accounts.' }))
  screen.getByRole('checkbox', { name: /I have reviewed/ }).focus(); await user.keyboard(' ')
  screen.getByRole('button', { name: 'Start a new bank account' }).focus(); await user.keyboard('{Enter}'); await screen.findByLabelText('Account name')
  expect(document.activeElement).toBe(screen.getByRole('heading', { name: 'Give your account a place.' }))
  screen.getByLabelText('Account name').focus(); await user.keyboard('Family account')
  screen.getByRole('checkbox', { name: 'USD' }).focus(); await user.keyboard(' ')
  screen.getByRole('checkbox', { name: 'INR' }).focus(); await user.keyboard(' ')
  expect((await axe.run(container, { rules: { 'color-contrast': { enabled: false } } })).violations).toEqual([])
  screen.getByRole('button', { name: 'Create bank account' }).focus(); await user.keyboard('{Enter}'); await screen.findByRole('heading', { name: 'Creation confirmed.' })
  expect(JSON.parse(String(creates()[0]![1]!.body)).currencies).toEqual(['INR', 'USD'])
  expect((await axe.run(container, { rules: { 'color-contrast': { enabled: false } } })).violations).toEqual([])
  expect(storage).not.toHaveBeenCalled(); expect(readStorage).not.toHaveBeenCalled()
})

it('keeps a query outage distinct from uncertain creation and does not automatically retry', async () => {
  override('bank-account-setup/query', () => response({}, 503))
  await openDirectory(); fireEvent.click(screen.getByRole('button', { name: 'Add bank account' }))
  await screen.findByText('Saved setup could not be checked.')
  expect(screen.queryByRole('button', { name: 'Retry the same save' })).toBeNull(); expect(creates()).toHaveLength(0); expect(queries()).toHaveLength(1)
  expect(crypto.randomUUID).not.toHaveBeenCalled()
})
it('cannot abandon uncertainty and start a new intent without directory review', async () => {
  override('bank-account-setup/create', () => response({}, 503))
  await openForm(); fill(); fireEvent.click(screen.getByRole('button', { name: 'Create bank account' })); await screen.findByRole('heading', { name: 'The save is not confirmed.' })
  fireEvent.click(screen.getByRole('button', { name: 'Close setup' }))
  expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Add bank account' }))
  fireEvent.click(screen.getByRole('button', { name: 'Add bank account' })); await screen.findByRole('heading', { name: 'Review your saved accounts.' })
  expect(screen.queryByLabelText('Account name')).toBeNull(); expect((screen.getByRole('button', { name: 'Start a new bank account' }) as HTMLButtonElement).disabled).toBe(true)
  expect(creates()).toHaveLength(1); expect(crypto.randomUUID).toHaveBeenCalledTimes(1)
})
it('clears uncertain request details immediately on offline', async () => {
  override('bank-account-setup/create', () => response({}, 503))
  await openForm(); fill(); fireEvent.click(screen.getByRole('button', { name: 'Create bank account' })); await screen.findByRole('heading', { name: 'The save is not confirmed.' })
  fireEvent(window, new Event('offline')); expect(document.querySelector('.bs-panel')).toBeNull(); expect(document.body.textContent).not.toContain('Everyday account')
  expect(creates()).toHaveLength(1)
})
it('retains the confirmed receipt if the directory refresh is temporarily unavailable', async () => {
  await openForm(); override('accounts/query', () => response({}, 503)); await create()
  expect(screen.getByRole('complementary', { name: 'Original creation receipt' })).toBeTruthy()
  expect(screen.getByText('Accounts are unavailable right now.')).toBeTruthy()
  expect(screen.getByText(/directory below shows its refresh status/)).toBeTruthy(); expect(creates()).toHaveLength(1)
})

it('requires a fresh directory review if another tab advances while the prior review is open', async () => {
  override('bank-account-setup/create', () => response({}, 409))
  await openForm(); fill(); fireEvent.click(screen.getByRole('button', { name: 'Create bank account' })); await screen.findByRole('heading', { name: 'Review your saved accounts.' })
  fireEvent.click(screen.getByRole('checkbox', { name: /I have reviewed/ }))
  commit(bankSetupCommand(id(500), 0, { ...input(), label: 'Newly saved in another tab' }))
  fireEvent.click(screen.getByRole('button', { name: 'Start a new bank account' })); await screen.findByRole('heading', { name: 'Review your saved accounts.' })
  expect(screen.queryByLabelText('Account name')).toBeNull(); expect((screen.getByRole('checkbox', { name: /I have reviewed/ }) as HTMLInputElement).checked).toBe(false)
  expect(within(screen.getByRole('list', { name: 'Saved accounts' })).getByText('Newly saved in another tab')).toBeTruthy(); expect(creates()).toHaveLength(1)
})
it('discards a late malformed setup payload after navigation without parsing it into the new view', async () => {
  let finish!: (value: Response) => void
  override('bank-account-setup/query', () => new Promise(resolve => { finish = resolve }))
  await openDirectory(); fireEvent.click(screen.getByRole('button', { name: 'Add bank account' })); await screen.findByText('Checking saved bank account setup…')
  fireEvent.click(within(screen.getByRole('navigation', { name: 'Workspace navigation' })).getByRole('button', { name: 'Overview' }))
  await act(async () => finish(response({ private: 'late invalid payload' })))
  expect(auth.snapshot().screen.kind).toBe('workspace'); expect(document.body.textContent).not.toContain('late invalid payload'); expect(creates()).toHaveLength(0)
})

it('requires a refreshed directory and explicit review even for the first account in an empty workspace', async () => {
  await openDirectory()
  const before = fetchMock.mock.calls.filter(([path]) => path === '/api/v1/finance/accounts/query').length
  fireEvent.click(screen.getByRole('button', { name: 'Add bank account' })); await screen.findByRole('heading', { name: 'Review your saved accounts.' })
  expect(screen.getByText('Review the saved directory before creating an account. An account missing from this page may be on another page.')).toBeTruthy()
  expect(fetchMock.mock.calls.filter(([path]) => path === '/api/v1/finance/accounts/query')).toHaveLength(before + 1)
  expect(screen.queryByLabelText('Account name')).toBeNull(); expect(screen.queryByRole('complementary', { name: 'Latest saved creation receipt' })).toBeNull()
  const start = screen.getByRole('button', { name: 'Start a new bank account' }) as HTMLButtonElement
  expect(start.disabled).toBe(true); fireEvent.click(start)
  expect(creates()).toHaveLength(0); expect(crypto.randomUUID).not.toHaveBeenCalled()
  await confirmDirectoryReview(); await screen.findByLabelText('Account name'); await create()
  expect(creates()).toHaveLength(1)
})
it('does not replay a pending create on remount and requires fresh directory review before a new intent', async () => {
  let finish!: (value: Response) => void, pending!: BankSetupCommand, delayFirst = true
  override('bank-account-setup/create', body => {
    if (delayFirst) { delayFirst = false; pending = body; return new Promise(resolve => { finish = resolve }) }
    return response(commit(body))
  })
  await openForm(); fill('Original pending account'); fireEvent.click(screen.getByRole('button', { name: 'Create bank account' })); await screen.findByText('Saving account details…')
  const nav = within(screen.getByRole('navigation', { name: 'Workspace navigation' }))
  fireEvent.click(nav.getByRole('button', { name: 'Overview' })); fireEvent.click(nav.getByRole('button', { name: 'Accounts' }))
  expect(document.querySelector('.bs-panel')).toBeNull(); expect(creates()).toHaveLength(1)
  await act(async () => finish(response(commit(pending))))
  await waitFor(() => expect(auth.snapshot().busy).toBe(false))
  expect(document.querySelector('.bs-panel')).toBeNull(); expect(creates()).toHaveLength(1)
  const directoryReads = fetchMock.mock.calls.filter(([path]) => path === '/api/v1/finance/accounts/query').length
  fireEvent.click(screen.getByRole('button', { name: 'Add bank account' })); await screen.findByRole('heading', { name: 'Review your saved accounts.' })
  expect(fetchMock.mock.calls.filter(([path]) => path === '/api/v1/finance/accounts/query')).toHaveLength(directoryReads + 1)
  expect(within(screen.getByRole('list', { name: 'Saved accounts' })).getByText('Original pending account')).toBeTruthy()
  expect(screen.getByText(/latest receipt does not prove an older unconfirmed request failed/i)).toBeTruthy()
  expect(screen.queryByLabelText('Account name')).toBeNull(); expect(screen.queryByRole('button', { name: 'Retry the same save' })).toBeNull()
  const start = screen.getByRole('button', { name: 'Start a new bank account' }) as HTMLButtonElement
  expect(start.disabled).toBe(true); fireEvent.click(start); expect(creates()).toHaveLength(1); expect(crypto.randomUUID).toHaveBeenCalledTimes(1)
  await confirmDirectoryReview(); await screen.findByLabelText('Account name'); await create('Reviewed new account')
  expect(creates()).toHaveLength(2); expect(crypto.randomUUID).toHaveBeenCalledTimes(2)
  const first = JSON.parse(String(creates()[0]![1]!.body)), next = JSON.parse(String(creates()[1]![1]!.body))
  expect(next.intent_id).not.toBe(first.intent_id); expect(next.expected_revision).toBe(1); expect(next.label).toBe('Reviewed new account')
})
