import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AuthController, parseSession } from '../../workspace/src/auth'

const factor = '40000000-0000-4000-8000-000000000001'
const session = () => ({ status: 'authenticated', expires_at: new Date(Date.now() + 28_800_000).toISOString(), idle_expires_at: new Date(Date.now() + 900_000).toISOString(), fresh_until: new Date(Date.now() + 300_000).toISOString(), factors: [factor], unverified_factors: [] })
function response(data: unknown, status = 200, extra: Record<string, string> = {}) { return new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store', Date: new Date().toUTCString(), ...extra } }) }
const ready = () => response({ status: 'ready', recovery_email_enabled: true })
const denied = () => response({}, 401)
const fetchMock = vi.fn<typeof fetch>()
let controller: AuthController
let stop: (() => void) | undefined

beforeEach(() => {
  document.cookie = 'trading_dev_csrf=synthetic-csrf-value-long-enough; Path=/'
  vi.stubGlobal('fetch', fetchMock)
  fetchMock.mockReset()
  controller = new AuthController()
})
afterEach(() => { stop?.(); stop = undefined; vi.useRealTimers(); vi.unstubAllGlobals(); document.cookie = 'trading_dev_csrf=; Max-Age=0; Path=/' })

it('starts closed, bootstraps CSRF, restores only a checked session, and never uses storage', async () => {
  const local = vi.spyOn(Storage.prototype, 'setItem')
  fetchMock.mockResolvedValueOnce(ready()).mockResolvedValueOnce(response(session()))
  expect(controller.snapshot().screen.kind).toBe('checking')
  await controller.bootstrap()
  expect(controller.snapshot().screen.kind).toBe('workspace')
  expect(fetchMock.mock.calls[1]?.[1]).toMatchObject({ credentials: 'same-origin', mode: 'same-origin', redirect: 'error', cache: 'no-store', headers: { 'X-CSRFToken': 'synthetic-csrf-value-long-enough' } })
  expect(local).not.toHaveBeenCalled()
})

it('requires MFA, then checks the active session before exposing the workspace', async () => {
  fetchMock.mockResolvedValueOnce(response({ status: 'mfa_required', factors: [factor], setup_key: 'JBSWY3DPEHPK3PXP' }))
  await controller.login('owner@example.invalid', 'synthetic-password')
  expect(controller.snapshot().screen.kind).toBe('mfa')
  fetchMock.mockResolvedValueOnce(response({ status: 'authenticated' })).mockResolvedValueOnce(response(session()))
  await controller.verify(factor, '123456')
  expect(controller.snapshot().screen.kind).toBe('workspace')
  expect(JSON.stringify(controller.snapshot())).not.toContain('JBSWY3DPEHPK3PXP')
  expect(JSON.stringify(controller.snapshot())).not.toContain('synthetic-password')
})

it('consumes a failed MFA attempt without keeping the setup key', async () => {
  fetchMock.mockResolvedValueOnce(response({ status: 'mfa_required', factors: [factor], setup_key: 'JBSWY3DPEHPK3PXP' })).mockResolvedValueOnce(denied())
  await controller.login('owner@example.invalid', 'synthetic-password')
  await controller.verify(factor, '000000')
  expect(controller.snapshot().screen.kind).toBe('login')
  expect(JSON.stringify(controller.snapshot())).not.toContain('setup_key')
})

it.each([401, 403, 429, 500, 503])('hides the workspace on a %s session check and does not retry', async status => {
  fetchMock.mockResolvedValueOnce(ready()).mockResolvedValueOnce(response(session())).mockResolvedValueOnce(response({ error: '<script>do-not-render</script>' }, status))
  await controller.bootstrap()
  await controller.check()
  expect(controller.snapshot().screen.kind).not.toBe('workspace')
  expect(JSON.stringify(controller.snapshot())).not.toContain('script')
  expect(fetchMock).toHaveBeenCalledTimes(3)
})

it('discards a stale session response after local lock', async () => {
  fetchMock.mockResolvedValueOnce(ready()).mockResolvedValueOnce(response(session()))
  await controller.bootstrap()
  let resolve!: (value: Response) => void
  fetchMock.mockImplementationOnce(() => new Promise(done => { resolve = done }))
  const checking = controller.check()
  controller.lock()
  resolve(response(session()))
  await checking
  expect(controller.snapshot().screen.kind).toBe('login')
})

it('serializes requests within a tab', async () => {
  let resolve!: (value: Response) => void
  fetchMock.mockImplementationOnce(() => new Promise(done => { resolve = done }))
  const login = controller.login('owner@example.invalid', 'synthetic-password')
  await controller.login('owner@example.invalid', 'synthetic-password')
  expect(fetchMock).toHaveBeenCalledTimes(1)
  resolve(response({ status: 'mfa_required', factors: [factor] }))
  await login
})

it('locks immediately on logout, confirms revocation, and discards older checks', async () => {
  fetchMock.mockResolvedValueOnce(ready()).mockResolvedValueOnce(response(session()))
  await controller.bootstrap()
  let resolve!: (value: Response) => void
  fetchMock.mockImplementationOnce(() => new Promise(done => { resolve = done })).mockResolvedValueOnce(response({ status: 'signed_out', provider_cleanup: 'complete' }))
  const checking = controller.check()
  const logout = controller.logout(true)
  expect(controller.snapshot().screen.kind).not.toBe('workspace')
  await logout
  resolve(response(session()))
  await checking
  expect(controller.snapshot().screen.kind).toBe('login')
  expect(fetchMock.mock.calls.at(-1)?.[0]).toBe('/api/v1/auth/revoke-all')
})

it('keeps uncertain logout distinct and retries the original all-session operation', async () => {
  fetchMock.mockRejectedValueOnce(new TypeError('network failed'))
  await controller.logout(true)
  expect(controller.snapshot().screen).toMatchObject({ kind: 'blocked', reason: 'signout' })
  fetchMock.mockResolvedValueOnce(response({ status: 'signed_out', provider_cleanup: 'unavailable' }))
  await controller.retryLogout()
  expect(fetchMock.mock.calls[1]?.[0]).toBe('/api/v1/auth/revoke-all')
  expect(controller.snapshot().screen).toMatchObject({ kind: 'login', message: expect.stringContaining('Provider cleanup is unavailable') })
})

it('keeps recovery restricted through email, MFA and password change', async () => {
  fetchMock.mockResolvedValueOnce(ready()).mockResolvedValueOnce(denied())
  await controller.bootstrap(); controller.recovery()
  fetchMock.mockResolvedValueOnce(response({ status: 'recovery_requested' }, 202))
  await controller.requestRecovery('owner@example.invalid')
  expect(controller.snapshot().screen).toMatchObject({ kind: 'recovery', sent: true })
  fetchMock.mockResolvedValueOnce(response({ status: 'mfa_required', factors: [factor] }))
  await controller.verifyRecovery('owner@example.invalid', '123456')
  fetchMock.mockResolvedValueOnce(response({ status: 'password_required' }))
  await controller.verify(factor, '123456')
  expect(controller.snapshot().screen.kind).toBe('password')
  fetchMock.mockResolvedValueOnce(response({ status: 'sign_in_required' }))
  await controller.password('a synthetic new password')
  expect(controller.snapshot().screen.kind).toBe('login')
  expect(fetchMock.mock.calls.filter(([path]) => path === '/api/v1/auth/session')).toHaveLength(1)
})

it.each([
  { status: 'authenticated', access_token: 'not-allowed' },
  { status: 'mfa_required', factors: [] },
  { status: 'mfa_required', factors: ['bad-id'] },
  { status: 'mfa_required', factors: [factor], setup_key: '<script>' },
  { status: 'mfa_required', factors: [factor], refresh_token: 'not-allowed' },
])('rejects unexpected provider or malformed fields %#', async data => {
  fetchMock.mockResolvedValueOnce(response(data))
  await controller.login('owner@example.invalid', 'synthetic-password')
  expect(controller.snapshot().screen).toMatchObject({ kind: 'blocked', reason: 'protocol' })
})

it.each<Record<string, string>>([{ 'Content-Type': 'text/html' }, { 'Cache-Control': 'public' }, { Date: 'invalid' }])('rejects unsafe response headers %#', async headers => {
  fetchMock.mockResolvedValueOnce(response({ status: 'ready', recovery_email_enabled: false }, 200, headers))
  await controller.bootstrap()
  expect(controller.snapshot().screen).toMatchObject({ kind: 'blocked', reason: 'protocol' })
})

it('rejects oversized responses and missing CSRF without posting credentials', async () => {
  fetchMock.mockResolvedValueOnce(response({ extra: 'a'.repeat(9000) }))
  await controller.bootstrap()
  expect(controller.snapshot().screen).toMatchObject({ reason: 'protocol' })
  document.cookie = 'trading_dev_csrf=; Max-Age=0; Path=/'
  await controller.login('owner@example.invalid', 'synthetic-password')
  expect(fetchMock).toHaveBeenCalledTimes(1)
  expect(controller.snapshot().screen).toMatchObject({ reason: 'forbidden' })
})

it('checks revocation periodically without extending idle time, and only activity extends it', async () => {
  vi.useFakeTimers()
  fetchMock.mockImplementation(async path => path === '/api/v1/auth/bootstrap' ? ready() : response(session()))
  stop = controller.start()
  await vi.advanceTimersByTimeAsync(1)
  await vi.advanceTimersByTimeAsync(60_000)
  expect(fetchMock.mock.calls.filter(([path]) => path === '/api/v1/auth/session')).toHaveLength(2)
  expect(fetchMock.mock.calls.some(([path]) => path === '/api/v1/auth/session/activity')).toBe(false)
  await controller.activity()
  expect(fetchMock.mock.calls.at(-1)?.[0]).toBe('/api/v1/auth/session/activity')
})

it('expires pending MFA locally and clears enrollment material', async () => {
  vi.useFakeTimers()
  fetchMock.mockResolvedValueOnce(ready()).mockResolvedValueOnce(denied())
  stop = controller.start(); await vi.advanceTimersByTimeAsync(1)
  fetchMock.mockResolvedValueOnce(response({ status: 'mfa_required', factors: [factor], setup_key: 'JBSWY3DPEHPK3PXP' }))
  await controller.login('owner@example.invalid', 'synthetic-password')
  fetchMock.mockResolvedValueOnce(denied())
  await vi.advanceTimersByTimeAsync(301_000)
  expect(controller.snapshot().screen).toMatchObject({ kind: 'login', message: expect.stringContaining('expired') })
})

it('can restart after effect cleanup without leaving a busy session check', async () => {
  fetchMock.mockImplementation(async path => path === '/api/v1/auth/bootstrap' ? ready() : denied())
  controller.start()()
  stop = controller.start()
  await vi.waitFor(() => expect(controller.snapshot().screen.kind).toBe('login'))
  expect(controller.snapshot().busy).toBe(false)
})

describe('server deadlines', () => {
  it('uses server time even when the browser wall clock differs', () => {
    const data = session(), now = Date.now()
    vi.spyOn(Date, 'now').mockReturnValue(now + 86_400_000)
    expect(parseSession(data, now).status).toBe('authenticated')
  })
  it.each(['not-a-date', -1000, 900_001])('rejects invalid or out-of-bounds idle expiry %s', value => {
    const now = Date.now()
    const idle = typeof value === 'number' ? new Date(now + value).toISOString() : value
    expect(() => parseSession({ ...session(), idle_expires_at: idle }, now)).toThrow()
  })
})

it('aborts a stalled network request at its deadline and remains locked', async () => {
  vi.useFakeTimers()
  fetchMock.mockImplementationOnce((_, options) => new Promise((_, reject) => {
    options!.signal!.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
  }))
  const checking = controller.bootstrap()
  await vi.advanceTimersByTimeAsync(20_001)
  await checking
  expect(controller.snapshot().screen).toMatchObject({ kind: 'blocked', reason: 'unavailable' })
  expect(controller.snapshot().busy).toBe(false)
})

it('locks other tabs using a constant signal without sending any identity or credential', async () => {
  const sent: unknown[] = []
  let channel!: { onmessage?: (event: MessageEvent) => void }
  vi.stubGlobal('BroadcastChannel', class {
    onmessage?: (event: MessageEvent) => void
    constructor() { channel = this }
    postMessage(message: unknown) { sent.push(message) }
    close() {}
  })
  fetchMock.mockResolvedValueOnce(ready()).mockResolvedValueOnce(response(session()))
  stop = controller.start()
  await vi.waitFor(() => expect(controller.snapshot().screen.kind).toBe('workspace'))
  channel.onmessage?.(new MessageEvent('message', { data: 'locked' }))
  expect(controller.snapshot().screen.kind).toBe('login')
  fetchMock.mockResolvedValueOnce(response({ status: 'signed_out', provider_cleanup: 'complete' }))
  await controller.logout()
  expect(sent).toEqual(['locked'])
})

it.each(['restore', 'logout'])('shows a retryable closed state when %s times out', async operation => {
  vi.useFakeTimers()
  if (operation === 'restore') fetchMock.mockResolvedValueOnce(ready())
  fetchMock.mockImplementationOnce((_, options) => new Promise((_, reject) => {
    options!.signal!.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
  }))
  const pending = operation === 'restore' ? controller.bootstrap() : controller.logout()
  await vi.advanceTimersByTimeAsync(20_001)
  await pending
  expect(controller.snapshot().screen).toMatchObject({ kind: 'blocked', reason: operation === 'restore' ? 'unavailable' : 'signout' })
  expect(controller.snapshot().busy).toBe(false)
})
