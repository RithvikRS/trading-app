import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { AuthController, parseSession } from '../../workspace/src/auth'

const context = 'a'.repeat(64), replacement = 'b'.repeat(64)
const prefs = { theme: 'dark', display_currency: 'USD', amount_masked: false, revision: 1 } as const
const session = () => ({ status: 'authenticated', workspace_context: context, expires_at: new Date(Date.now() + 28_800_000).toISOString(), idle_expires_at: new Date(Date.now() + 900_000).toISOString(), fresh_until: new Date(Date.now() + 300_000).toISOString(), factors: ['40000000-0000-4000-8000-000000000001'], unverified_factors: [] })
function response(data: unknown, status = 200) { return new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store', Date: new Date().toUTCString() } }) }
const fetchMock = vi.fn<typeof fetch>()
let auth: AuthController
beforeEach(() => {
  document.cookie = 'trading_dev_csrf=synthetic-csrf-value-long-enough; Path=/'
  vi.stubGlobal('fetch', fetchMock); fetchMock.mockReset(); auth = new AuthController()
  fetchMock.mockImplementation(async path => path === '/api/v1/auth/bootstrap' ? response({ status: 'ready', recovery_email_enabled: false }) : path === '/api/v1/auth/session' ? response(session()) : path === '/api/v1/preferences' ? response(prefs) : response({}, 401))
})
afterEach(() => { auth.lock(); vi.unstubAllGlobals(); document.cookie = 'trading_dev_csrf=; Max-Age=0; Path=/' })

it('binds initial preference reads, reloads, and saves to the checked session context', async () => {
  await auth.bootstrap()
  await auth.reloadPreferences()
  fetchMock.mockResolvedValueOnce(response({ ...prefs, theme: 'light', revision: 2 }))
  await auth.savePreferences({ ...prefs, theme: 'light' })
  const requests = fetchMock.mock.calls.filter(([path]) => path === '/api/v1/preferences')
  expect(requests).toHaveLength(3)
  for (const [, options] of requests) expect(options?.headers).toMatchObject({ 'X-Workspace-Context': context })
  expect(auth.snapshot().screen).toMatchObject({ kind: 'workspace', preferences: { theme: 'light', revision: 2 } })
})

it('withholds workspace activation when the cookie changes between session and preferences', async () => {
  fetchMock.mockResolvedValueOnce(response({ status: 'ready', recovery_email_enabled: false })).mockResolvedValueOnce(response(session())).mockResolvedValueOnce(response({ error: 'workspace_context_changed' }, 412))
  await auth.bootstrap()
  expect(auth.snapshot().screen).toMatchObject({ kind: 'blocked', reason: 'context' })
  expect(JSON.stringify(auth.snapshot())).not.toContain('preferences')
})

it('clears the old workspace when a periodic check sees a replacement context', async () => {
  await auth.bootstrap()
  fetchMock.mockResolvedValueOnce(response({ ...session(), workspace_context: replacement }))
  await auth.check()
  expect(auth.snapshot().screen).toMatchObject({ kind: 'blocked', reason: 'context' })
  expect(JSON.stringify(auth.snapshot())).not.toContain(context)
  expect(JSON.stringify(auth.snapshot())).not.toContain('USD')
})

it('keeps a normal renewal stable and treats a stale-context save separately from revision conflict', async () => {
  await auth.bootstrap(); await auth.check()
  expect(auth.snapshot().screen).toMatchObject({ kind: 'workspace', preferences: prefs })
  fetchMock.mockResolvedValueOnce(response({}, 412))
  await auth.savePreferences({ ...prefs, theme: 'light' })
  expect(auth.snapshot().screen).toMatchObject({ kind: 'blocked', reason: 'context' })
  expect(JSON.stringify(auth.snapshot())).not.toContain('conflict')
  expect(fetchMock.mock.calls.filter(([, options]) => options?.method === 'PUT')).toHaveLength(1)
})

it('reloads the replacement preferences only through a fresh checked bootstrap', async () => {
  await auth.bootstrap()
  fetchMock.mockResolvedValueOnce(response({}, 412)); await auth.reloadPreferences()
  fetchMock.mockResolvedValueOnce(response({ status: 'ready', recovery_email_enabled: false })).mockResolvedValueOnce(response({ ...session(), workspace_context: replacement })).mockResolvedValueOnce(response({ ...prefs, amount_masked: true }))
  await auth.bootstrap()
  expect(fetchMock.mock.calls.at(-1)?.[1]?.headers).toMatchObject({ 'X-Workspace-Context': replacement })
  expect(auth.snapshot().screen).toMatchObject({ kind: 'workspace', preferences: { amount_masked: true }, session: { workspace_context: replacement } })
})

it.each([undefined, null, '', 'A'.repeat(64), 'a'.repeat(63), 123])('rejects a missing or malformed view context %#', value => {
  expect(() => parseSession({ ...session(), workspace_context: value }, Date.now())).toThrow()
})

it('does not send preference reads without an active workspace', async () => {
  await auth.reloadPreferences(); expect(fetchMock).not.toHaveBeenCalled()
})

it('broadcasts only the constant lock signal before replacing a shared sign-in', async () => {
  const sent: unknown[] = []
  vi.stubGlobal('BroadcastChannel', class { postMessage(value: unknown) { sent.push(value) } close() {} })
  const stop = auth.start()
  try {
    await vi.waitFor(() => expect(auth.snapshot().screen.kind).toBe('workspace'))
    await auth.login('synthetic@example.invalid', 'synthetic password')
    await auth.verifyRecovery('synthetic@example.invalid', '123456')
    expect(sent).toEqual(['locked', 'locked'])
    expect(JSON.stringify(sent)).not.toContain(context)
  } finally { stop() }
})
