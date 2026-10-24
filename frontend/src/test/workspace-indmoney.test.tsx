import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import axe from 'axe-core'
import Workspace from '../../workspace/src/Workspace'
import { AuthController } from '../../workspace/src/auth'
import { authorizationTarget, parseConnection } from '../../workspace/src/indmoney'

const status = (state = 'disconnected', complete = false) => ({ status: state, can_complete: complete, expires_at: null, financial_access_enabled: false })
const session = () => ({ status: 'authenticated', workspace_context: 'a'.repeat(64), expires_at: new Date(Date.now() + 28_800_000).toISOString(), idle_expires_at: new Date(Date.now() + 900_000).toISOString(), fresh_until: new Date(Date.now() + 300_000).toISOString(), factors: ['40000000-0000-4000-8000-000000000001'], unverified_factors: [] })
const target = () => 'https://mcp.indmoney.com/authorize?' + new URLSearchParams({ response_type: 'code', client_id: 'synthetic-client', redirect_uri: 'https://127.0.0.1:8443/api/v1/connections/indmoney/callback', scope: 'portfolio:read', state: 's'.repeat(43), code_challenge: 'c'.repeat(43), code_challenge_method: 'S256', resource: 'https://mcp.indmoney.com/mcp' })
function response(data: unknown, code = 200) { return new Response(JSON.stringify(data), { status: code, headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store', Date: new Date().toUTCString() } }) }
let auth: AuthController
const fetchMock = vi.fn<typeof fetch>(), navigate = vi.fn()
beforeEach(() => {
  document.cookie = 'trading_dev_csrf=synthetic-csrf-value-long-enough; Path=/'
  navigate.mockReset(); auth = new AuthController(navigate)
  vi.stubGlobal('fetch', fetchMock); fetchMock.mockReset()
  fetchMock.mockImplementation(async path => {
    if (path === '/api/v1/auth/bootstrap') return response({ status: 'ready', recovery_email_enabled: false })
    if (path === '/api/v1/auth/session') return response(session())
    if (path === '/api/v1/preferences') return response({ theme: 'light', display_currency: 'INR', amount_masked: true, revision: 0 })
    if (path === '/api/v1/connections/indmoney') return response(status())
    if (path === '/api/v1/connections/indmoney/authorize') return response({ authorization_url: target() })
    return response({}, 404)
  })
})
afterEach(() => { auth.lock(); vi.unstubAllGlobals(); document.cookie = 'trading_dev_csrf=; Max-Age=0; Path=/'; delete document.documentElement.dataset.theme })

it('uses same-origin CSRF/context requests and navigates only to the reviewed authorization endpoint', async () => {
  await auth.connection('authorize'); expect(fetchMock).not.toHaveBeenCalled()
  await auth.bootstrap(); await auth.connection('status'); await auth.connection('authorize')
  expect(navigate).toHaveBeenCalledExactlyOnceWith(target())
  expect(fetchMock.mock.calls.at(-1)).toEqual(['/api/v1/connections/indmoney/authorize', expect.objectContaining({ method: 'POST', body: '{}', credentials: 'same-origin', redirect: 'error', cache: 'no-store', headers: expect.objectContaining({ 'X-CSRFToken': 'synthetic-csrf-value-long-enough', 'X-Workspace-Context': 'a'.repeat(64) }) })])
  expect(JSON.stringify(auth.snapshot())).not.toContain('synthetic-client')
})

it.each(['lock', 'offline', 'suspend'] as const)('drops late authorization responses after %s', async method => {
  await auth.bootstrap()
  let done!: (response: Response) => void
  fetchMock.mockImplementationOnce(() => new Promise(resolve => { done = resolve }))
  const pending = auth.connection('authorize')
  auth[method](); done(response({ authorization_url: target() })); await pending
  expect(navigate).not.toHaveBeenCalled()
  expect(auth.snapshot().screen.kind).not.toBe('workspace')
})

it.each([404, 409, 429, 503])('keeps a valid workspace for connector status %s and does not retry a mutation', async code => {
  await auth.bootstrap(); fetchMock.mockResolvedValueOnce(response({}, code))
  await auth.connection('complete')
  expect(auth.snapshot().screen).toMatchObject({ kind: 'workspace', connection: { kind: code === 404 ? 'unconfigured' : 'failed' } })
  expect(fetchMock.mock.calls.filter(([path]) => path === '/api/v1/connections/indmoney/complete')).toHaveLength(1)
})

it.each([401, 403, 412])('locks the workspace for authentication or context rejection %s', async code => {
  await auth.bootstrap(); fetchMock.mockResolvedValueOnce(response({}, code)); await auth.connection('status')
  expect(auth.snapshot().screen.kind).not.toBe('workspace')
})

it('finishes a callback through a protected POST then reads status', async () => {
  await auth.bootstrap(); fetchMock.mockResolvedValueOnce(response({ status: 'authorized' })).mockResolvedValueOnce(response(status('authorized')))
  await auth.connection('complete')
  expect(auth.snapshot().screen).toMatchObject({ connection: { kind: 'ready', value: status('authorized') } })
  expect(fetchMock.mock.calls.at(-2)?.[0]).toBe('/api/v1/connections/indmoney/complete')
  expect(fetchMock.mock.calls.at(-2)?.[1]?.body).toBe('{}')
})

it.each(['host', 'scope', 'callback', 'duplicate', 'pkce', 'userinfo', 'fragment'])('rejects substituted authorization destinations or permissions: %s', change => {
  const url = new URL(target())
  if (change === 'host') url.hostname = 'attacker.invalid'
  if (change === 'scope') url.searchParams.set('scope', 'orders:write')
  if (change === 'callback') url.searchParams.set('redirect_uri', 'https://attacker.invalid')
  if (change === 'duplicate') url.searchParams.append('state', 'a'.repeat(43))
  if (change === 'pkce') url.searchParams.set('code_challenge_method', 'plain')
  if (change === 'userinfo') url.username = 'attacker'
  if (change === 'fragment') url.hash = 'code=private'
  expect(() => authorizationTarget({ authorization_url: url.href })).toThrow()
})

it('rejects unexpected token fields and financial-access claims', () => {
  expect(() => parseConnection({ ...status(), access_token: 'private' })).toThrow()
  expect(() => parseConnection({ ...status(), financial_access_enabled: true })).toThrow()
})

it('shows explicit completion and disconnect controls with accessible states', async () => {
  const view = render(<Workspace controller={auth} />), user = userEvent.setup()
  await screen.findByRole('heading', { name: 'A fresh start.' })
  fetchMock.mockResolvedValueOnce(response(status('pending', true)))
  await user.click(screen.getByRole('button', { name: 'Check connection status' }))
  expect((await screen.findByRole('button', { name: 'Finish authorization' }) as HTMLButtonElement).disabled).toBe(false)
  fetchMock.mockResolvedValueOnce(response({ status: 'authorized' })).mockResolvedValueOnce(response(status('authorized')))
  await user.click(screen.getByRole('button', { name: 'Finish authorization' }))
  expect(await screen.findByText('Authorization saved')).not.toBeNull()
  expect(screen.getByText(/Account identity, holdings, history/)).not.toBeNull()
  await user.click(screen.getByRole('button', { name: 'Disconnect' }))
  fetchMock.mockResolvedValueOnce(response({ status: 'disconnected', provider_cleanup: 'unavailable' }))
  await user.click(screen.getByRole('button', { name: 'Disconnect INDmoney' }))
  expect((await screen.findByRole('alert')).textContent).toContain('Local access is disabled')
  expect((await axe.run(view.container, { rules: { 'color-contrast': { enabled: false } } })).violations).toEqual([])
  act(() => auth.lock())
  expect(screen.queryByRole('heading', { name: 'INDmoney authorization' })).toBeNull()
})
