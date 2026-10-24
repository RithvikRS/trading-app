import { act, fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import axe from 'axe-core'
import Workspace from '../../workspace/src/Workspace'
import { AuthController } from '../../workspace/src/auth'
import { accountCursor, parseAccountPage } from '../../workspace/src/accounts'

const id = (n: number) => `50000000-0000-4000-8000-${String(n).padStart(12, '0')}`
const account = (n = 1) => ({ id: id(n), kind: 'bank', institution: 'hdfc', market: 'IN', label: `Synthetic account ${String.fromCharCode(64 + n)}`, currencies: ['INR'], revision: 1, state: 'active' })
const page = (start = 1, count = 1, more = false) => ({ items: Array.from({ length: count }, (_, i) => account(start + i)), next_after: more ? id(start + count - 1) : null })
const prefs = { theme: 'light', display_currency: 'INR', amount_masked: true, revision: 0 }
const session = () => ({ status: 'authenticated', workspace_context: 'a'.repeat(64), expires_at: new Date(Date.now() + 28_800_000).toISOString(), idle_expires_at: new Date(Date.now() + 900_000).toISOString(), fresh_until: new Date(Date.now() + 300_000).toISOString(), factors: [id(99)], unverified_factors: [] })
function response(data: unknown, status = 200, headers: Record<string, string> = {}) { return new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store', Date: new Date().toUTCString(), ...headers } }) }
const fetchMock = vi.fn<typeof fetch>()
let auth: AuthController
beforeEach(() => {
  document.cookie = 'trading_dev_csrf=synthetic-csrf-value-long-enough; Path=/'
  vi.stubGlobal('fetch', fetchMock); fetchMock.mockReset(); auth = new AuthController()
  fetchMock.mockImplementation(async path => {
    if (path === '/api/v1/auth/bootstrap') return response({ status: 'ready', recovery_email_enabled: false })
    if (path === '/api/v1/auth/session') return response(session())
    if (path === '/api/v1/preferences') return response(prefs)
    if (path === '/api/v1/finance/accounts/query') return response(page())
    return response({}, 404)
  })
})
afterEach(() => { auth.lock(); vi.useRealTimers(); vi.unstubAllGlobals(); document.cookie = 'trading_dev_csrf=; Max-Age=0; Path=/'; delete document.documentElement.dataset.theme })

it('loads only after authenticated entry and keeps all identity parameters in a bounded POST', async () => {
  const store = vi.spyOn(Storage.prototype, 'setItem')
  await auth.loadAccounts(); expect(fetchMock).not.toHaveBeenCalled()
  await auth.bootstrap(); expect(fetchMock).toHaveBeenCalledTimes(3)
  await auth.loadAccounts()
  expect(fetchMock.mock.calls.at(-1)).toEqual(['/api/v1/finance/accounts/query', expect.objectContaining({ method: 'POST', credentials: 'same-origin', mode: 'same-origin', redirect: 'error', cache: 'no-store', referrerPolicy: 'no-referrer', body: JSON.stringify({ limit: 25, after: null }), headers: expect.objectContaining({ 'X-CSRFToken': 'synthetic-csrf-value-long-enough', 'X-Workspace-Context': 'a'.repeat(64) }) })])
  expect(auth.snapshot().screen).toMatchObject({ kind: 'workspace', accounts: { kind: 'ready', page: page() } })
  expect(store).not.toHaveBeenCalled()
})

it('paginates without retaining old pages and reloads the exact previous cursor', async () => {
  await auth.bootstrap(); fetchMock.mockResolvedValueOnce(response(page(1, 25, true))); await auth.loadAccounts()
  fetchMock.mockResolvedValueOnce(response(page(26))); await auth.loadAccounts('next')
  expect(fetchMock.mock.calls.at(-1)?.[1]?.body).toBe(JSON.stringify({ limit: 25, after: id(25) }))
  expect(JSON.stringify(auth.snapshot())).not.toContain(account().label)
  fetchMock.mockResolvedValueOnce(response(page(1, 25, true))); await auth.loadAccounts('previous')
  expect(fetchMock.mock.calls.at(-1)?.[1]?.body).toBe(JSON.stringify({ limit: 25, after: null }))
})

it.each(['lock', 'offline', 'suspend'] as const)('discards loaded and late identity responses on %s', async action => {
  await auth.bootstrap(); await auth.loadAccounts()
  let resolve!: (value: Response) => void
  fetchMock.mockImplementationOnce(() => new Promise(done => { resolve = done }))
  const reading = auth.loadAccounts('refresh')
  expect(JSON.stringify(auth.snapshot())).not.toContain(account().label)
  auth[action](); resolve(response(page())); await reading
  expect(auth.snapshot().screen.kind).not.toBe('workspace')
  expect(JSON.stringify(auth.snapshot())).not.toContain(account().label)
})

it('rejects a delayed old response even after a new workspace session opens', async () => {
  await auth.bootstrap()
  let resolve!: (value: Response) => void
  fetchMock.mockImplementationOnce(() => new Promise(done => { resolve = done }))
  const reading = auth.loadAccounts()
  auth.lock(); await auth.bootstrap(); resolve(response(page())); await reading
  expect(auth.snapshot().screen).toMatchObject({ kind: 'workspace', accounts: { kind: 'idle' } })
})

it('keeps accounts through a normal session check and clears them when the sign-in changes', async () => {
  await auth.bootstrap(); await auth.loadAccounts(); await auth.check()
  expect(auth.snapshot().screen).toMatchObject({ kind: 'workspace', accounts: { kind: 'ready', page: page() } })
  fetchMock.mockResolvedValueOnce(response({ ...session(), workspace_context: 'b'.repeat(64) }))
  await auth.check()
  expect(auth.snapshot().screen).toMatchObject({ kind: 'blocked', reason: 'context' })
  expect(JSON.stringify(auth.snapshot())).not.toContain(account().label)
})

it.each([401, 403, 412])('locks the workspace and clears accounts on HTTP %s', async status => {
  await auth.bootstrap(); await auth.loadAccounts()
  fetchMock.mockResolvedValueOnce(response({ error: 'private server detail' }, status)); await auth.loadAccounts('refresh')
  expect(auth.snapshot().screen.kind).not.toBe('workspace')
  expect(JSON.stringify(auth.snapshot())).not.toContain('private server detail')
  expect(JSON.stringify(auth.snapshot())).not.toContain(account().label)
})

it.each([429, 503])('keeps a valid session but hides unavailable data on HTTP %s, allowing retry', async status => {
  await auth.bootstrap(); await auth.loadAccounts()
  fetchMock.mockResolvedValueOnce(response({ error: 'private server detail' }, status)); await auth.loadAccounts('refresh')
  expect(auth.snapshot().screen).toMatchObject({ kind: 'workspace', accounts: { kind: 'failed', limited: status === 429 } })
  expect(JSON.stringify(auth.snapshot())).not.toContain(account().label)
  await auth.loadAccounts('refresh'); expect(auth.snapshot().screen).toMatchObject({ accounts: { kind: 'ready' } })
})

it('expires a stalled read without leaving a loading page or retained accounts', async () => {
  vi.useFakeTimers(); await auth.bootstrap()
  fetchMock.mockImplementationOnce((_, options) => new Promise((_, reject) => { options!.signal!.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError'))) }))
  const reading = auth.loadAccounts(); await vi.advanceTimersByTimeAsync(20_001); await reading
  expect(auth.snapshot()).toMatchObject({ busy: false, screen: { kind: 'workspace', accounts: { kind: 'failed' } } })
})

it('locks if the local session expires while an account read is pending', async () => {
  vi.useFakeTimers(); await auth.bootstrap()
  let resolve!: (value: Response) => void
  fetchMock.mockImplementationOnce(() => new Promise(done => { resolve = done }))
  const reading = auth.loadAccounts(); await vi.advanceTimersByTimeAsync(900_000); resolve(response(page())); await reading
  expect(auth.snapshot().screen.kind).toBe('login')
})

it.each<Record<string, string>>([{ 'Cache-Control': 'public' }, { 'Content-Type': 'text/html' }])('rejects unsafe account response headers %#', async headers => {
  await auth.bootstrap(); fetchMock.mockResolvedValueOnce(response(page(), 200, headers)); await auth.loadAccounts()
  expect(auth.snapshot().screen).toMatchObject({ kind: 'blocked', reason: 'protocol' })
})

it('keeps the account byte bound separate from the smaller authentication bound', async () => {
  await auth.bootstrap(); fetchMock.mockResolvedValueOnce(response({ extra: 'x'.repeat(262_145) })); await auth.loadAccounts()
  expect(auth.snapshot().screen).toMatchObject({ kind: 'blocked', reason: 'protocol' })
})

it.each([
  { owner_id: id(99) }, { revision: 1.5 }, { revision: 9007199254740992 }, { state: 'connected' },
  { currencies: ['INR', 'INR'] }, { currencies: ['EUR'] }, { label: 'x'.repeat(65) }, { label: 'bad\u0000text' },
  { id: '00000000-0000-0000-0000-000000000000' }, { kind: 'credit_card' },
])('rejects unexpected or malformed account fields %#', changes => {
  expect(() => parseAccountPage({ items: [{ ...account(), ...changes }], next_after: null }, null)).toThrow('Account response is unavailable.')
})

it('rejects duplicate/reversed/before-cursor records, oversized pages, and false continuation', () => {
  for (const invalid of [{ items: [account(), account()], next_after: null }, { items: [account(2), account()], next_after: null }, page(1, 26), page(1, 1, true), { ...page(1, 25, true), next_after: id(26) }]) expect(() => parseAccountPage(invalid, null)).toThrow()
  expect(() => parseAccountPage(page(), id(2))).toThrow()
  expect(parseAccountPage(page(2), id(1))).toEqual(page(2))
  expect(accountCursor({ kind: 'ready', page: parseAccountPage(page(1, 25, true), null), cursor: { after: null, previous: Array(99).fill(null) } }, 'next')).toBeUndefined()
})

async function openDirectory() {
  const user = userEvent.setup()
  const result = render(<Workspace controller={auth} />)
  await screen.findByRole('heading', { name: 'A fresh start.' })
  await user.click(within(screen.getByRole('navigation', { name: 'Workspace navigation' })).getByRole('button', { name: 'Accounts' }))
  await screen.findByRole('heading', { name: 'Your accounts.' })
  return { ...result, user }
}

it('renders saved account identities accessibly, moves focus, and never fabricates amounts', async () => {
  const { container } = await openDirectory()
  await screen.findByText(account().label)
  expect(document.activeElement).toBe(screen.getByRole('heading', { name: 'Your accounts.' }))
  expect(screen.getByText('Native currencies')).toBeTruthy()
  expect(screen.queryByText(/₹|\$0|Rs\./)).toBeNull()
  expect((await axe.run(container, { rules: { 'color-contrast': { enabled: false } } })).violations).toEqual([])
  fireEvent(window, new Event('offline')); expect(screen.queryByText(account().label)).toBeNull()
})

it('renders imported labels as text and shows archived status without calling it a live connection', async () => {
  const previous = fetchMock.getMockImplementation()!
  fetchMock.mockImplementation((path, options) => path === '/api/v1/finance/accounts/query' ? Promise.resolve(response({ items: [{ ...account(), label: '<img src=x onerror=alert(1)>', state: 'archived' }], next_after: null })) : previous(path, options))
  const { container } = await openDirectory()
  await screen.findByText('<img src=x onerror=alert(1)>')
  expect(container.querySelector('.ws-account img')).toBeNull(); expect(screen.getByText('Archived')).toBeTruthy()
})

it('keeps empty and unavailable pages distinct and supports a healthy retry', async () => {
  const previous = fetchMock.getMockImplementation()!
  fetchMock.mockImplementation((path, options) => path === '/api/v1/finance/accounts/query' ? Promise.resolve(response(page(1, 0))) : previous(path, options))
  const { user } = await openDirectory(); await screen.findByText('No accounts saved yet.')
  fetchMock.mockResolvedValueOnce(response({}, 503)); await user.click(screen.getByRole('button', { name: 'Refresh accounts' }))
  await screen.findByRole('alert'); expect(screen.queryByText('No accounts saved yet.')).toBeNull()
  fetchMock.mockResolvedValueOnce(response(page())); await user.click(screen.getByRole('button', { name: 'Refresh accounts' }))
  await screen.findByText(account().label)
})

it('clears visible account data immediately on an explicit lock', async () => {
  await openDirectory(); await screen.findByText(account().label)
  act(() => auth.lock()); expect(screen.queryByText(account().label)).toBeNull()
})
