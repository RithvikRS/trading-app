import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { AuthController } from '../../workspace/src/auth'
import { parsePreferences } from '../../workspace/src/preferences'
import Workspace from '../../workspace/src/Workspace'

const defaults = { theme: 'light', display_currency: 'INR', amount_masked: true, revision: 0 } as const
const saved = { theme: 'dark', display_currency: 'USD', amount_masked: false, revision: 4 } as const
const factor = '40000000-0000-4000-8000-000000000001'
const session = () => ({ status: 'authenticated', expires_at: new Date(Date.now() + 28_800_000).toISOString(), idle_expires_at: new Date(Date.now() + 900_000).toISOString(), fresh_until: new Date(Date.now() + 300_000).toISOString(), factors: [factor], unverified_factors: [] })
function response(data: unknown, status = 200) { return new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store', Date: new Date().toUTCString() } }) }
const fetchMock = vi.fn<typeof fetch>()
let current: unknown
let controller: AuthController
beforeEach(() => {
  document.cookie = 'trading_dev_csrf=synthetic-csrf-value-long-enough; Path=/'
  current = defaults
  fetchMock.mockReset()
  fetchMock.mockImplementation(async path => response(path === '/api/v1/auth/bootstrap' ? { status: 'ready', recovery_email_enabled: false } : path === '/api/v1/preferences' ? current : session()))
  vi.stubGlobal('fetch', fetchMock)
  controller = new AuthController()
})
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); document.cookie = 'trading_dev_csrf=; Max-Age=0; Path=/'; delete document.documentElement.dataset.theme })

it('waits for preferences before revealing the workspace and uses no browser storage', async () => {
  const read = vi.spyOn(Storage.prototype, 'getItem'), write = vi.spyOn(Storage.prototype, 'setItem')
  let resolve!: (response: Response) => void
  fetchMock.mockImplementation(async path => path === '/api/v1/preferences' ? new Promise(done => { resolve = done }) : response(path === '/api/v1/auth/bootstrap' ? { status: 'ready', recovery_email_enabled: false } : session()))
  const opening = controller.bootstrap()
  await vi.waitFor(() => expect(resolve).toBeTypeOf('function'))
  expect(controller.snapshot().screen.kind).toBe('checking')
  resolve(response(saved)); await opening
  expect(controller.snapshot().screen).toMatchObject({ kind: 'workspace', preferences: saved })
  expect(read).not.toHaveBeenCalled(); expect(write).not.toHaveBeenCalled()
  expect(fetchMock.mock.calls.at(-1)).toMatchObject(['/api/v1/preferences', { method: 'GET', credentials: 'same-origin', cache: 'no-store', redirect: 'error', headers: { 'X-CSRFToken': 'synthetic-csrf-value-long-enough' } }])
})

it('uses system theme for an absent row while saved account settings take precedence', () => {
  vi.stubGlobal('matchMedia', () => ({ matches: true }))
  expect(parsePreferences(defaults)).toEqual({ ...defaults, theme: 'dark' })
  expect(parsePreferences({ ...defaults, revision: 1 })).toEqual({ ...defaults, revision: 1 })
})

it.each([
  {}, { ...saved, theme: ['light'] }, { ...saved, display_currency: ['INR'] }, { ...saved, owner_id: factor }, { ...saved, theme: 'system' }, { ...saved, display_currency: 'EUR' },
  { ...saved, amount_masked: 'false' }, { ...saved, revision: '1' }, { ...saved, revision: -1 },
  { ...saved, revision: 1.5 }, { ...saved, revision: Number.MAX_SAFE_INTEGER + 1 }, { ...saved, revision: 0 },
])('fails closed for malformed preference responses %#', async data => {
  current = data
  await controller.bootstrap()
  expect(controller.snapshot().screen).toMatchObject({ kind: 'blocked', reason: 'protocol' })
})

it.each([401, 403, 429, 500, 503])('does not fall back to defaults after a %s preference load', async status => {
  fetchMock.mockResolvedValueOnce(response({ status: 'ready', recovery_email_enabled: false })).mockResolvedValueOnce(response(session())).mockResolvedValueOnce(response({}, status))
  await controller.bootstrap()
  expect(controller.snapshot().screen.kind).not.toBe('workspace')
  expect(fetchMock).toHaveBeenCalledTimes(3)
})

it('sends a strict versioned update and applies it only after acknowledgement', async () => {
  await controller.bootstrap()
  let resolve!: (response: Response) => void
  fetchMock.mockImplementationOnce(() => new Promise(done => { resolve = done }))
  const changes = { theme: 'dark', display_currency: 'USD', amount_masked: false } as const
  const saving = controller.savePreferences(changes)
  expect(controller.snapshot().screen).toMatchObject({ preferences: defaults, preferenceStatus: 'saving' })
  expect(JSON.parse(String(fetchMock.mock.calls.at(-1)?.[1]?.body))).toEqual({ ...changes, revision: 0 })
  expect(fetchMock.mock.calls.at(-1)?.[1]?.method).toBe('PUT')
  resolve(response({ ...changes, revision: 1 })); await saving
  expect(controller.snapshot().screen).toMatchObject({ preferences: { ...changes, revision: 1 }, preferenceStatus: 'saved' })
})

it('preserves the saved state on conflict and requires an explicit reload before another save', async () => {
  await controller.bootstrap()
  fetchMock.mockResolvedValueOnce(response({ error: 'untrusted message' }, 409))
  await controller.savePreferences({ ...saved })
  expect(controller.snapshot().screen).toMatchObject({ preferences: defaults, preferenceStatus: 'conflict' })
  await controller.savePreferences({ ...saved })
  expect(fetchMock).toHaveBeenCalledTimes(4)
  current = saved
  await controller.reloadPreferences()
  expect(controller.snapshot().screen).toMatchObject({ preferences: saved, preferenceStatus: 'idle' })
})

it.each(['network', 'invalid', 'unauthorized', 'unavailable', 'wrong_revision'])('never retries or claims success after a %s save failure', async failure => {
  await controller.bootstrap()
  if (failure === 'network') fetchMock.mockRejectedValueOnce(new TypeError('synthetic network failure'))
  else fetchMock.mockResolvedValueOnce(response(failure === 'invalid' ? {} : { ...defaults, revision: 8 }, failure === 'unauthorized' ? 401 : failure === 'unavailable' ? 503 : 200))
  await controller.savePreferences(defaults)
  expect(controller.snapshot().screen.kind).not.toBe('workspace')
  expect(JSON.stringify(controller.snapshot())).toContain('not confirmed')
  expect(fetchMock).toHaveBeenCalledTimes(4)
})

it.each(['lock', 'suspend', 'offline'] as const)('discards late save responses after %s', async action => {
  await controller.bootstrap()
  let resolve!: (response: Response) => void
  fetchMock.mockImplementationOnce(() => new Promise(done => { resolve = done }))
  const saving = controller.savePreferences(defaults)
  controller[action]()
  resolve(response({ ...defaults, revision: 1 })); await saving
  expect(controller.snapshot().screen.kind).not.toBe('workspace')
  expect(JSON.stringify(controller.snapshot())).not.toContain('preferences')
})

it('rejects a delayed save acknowledgement after the local session deadline', async () => {
  await controller.bootstrap()
  const state = controller.snapshot().screen
  if (state.kind !== 'workspace') throw new Error('Expected workspace')
  let resolve!: (response: Response) => void
  fetchMock.mockImplementationOnce(() => new Promise(done => { resolve = done }))
  const saving = controller.savePreferences(defaults)
  vi.spyOn(performance, 'now').mockReturnValue(state.deadline + 1)
  resolve(response({ ...defaults, revision: 1 })); await saving
  expect(controller.snapshot().screen.kind).toBe('login')
})

it('times out a save without retry and clears all preference state', async () => {
  vi.useFakeTimers()
  await controller.bootstrap()
  fetchMock.mockImplementationOnce((_, options) => new Promise((_, reject) => options!.signal!.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))))
  const saving = controller.savePreferences(defaults)
  await vi.advanceTimersByTimeAsync(20_001); await saving
  expect(controller.snapshot().screen).toMatchObject({ kind: 'blocked', notice: expect.stringContaining('not confirmed') })
  expect(controller.snapshot().busy).toBe(false)
  expect(fetchMock).toHaveBeenCalledTimes(4)
})

it('keeps a draft during session checks, supports discard, and renders only saved settings', async () => {
  const user = userEvent.setup()
  render(<Workspace controller={controller} />)
  await screen.findByLabelText('Appearance')
  await user.selectOptions(screen.getByLabelText('Appearance'), 'dark')
  await user.selectOptions(screen.getByLabelText('Display currency'), 'USD')
  await user.selectOptions(screen.getByLabelText('Amount privacy'), 'visible')
  expect(document.documentElement.dataset.theme).toBe('light')
  expect(screen.getByText('Amounts hidden by default · INR display')).toBeTruthy()
  await act(() => controller.check())
  expect(screen.getByLabelText('Appearance')).toHaveProperty('value', 'dark')
  await user.click(screen.getByRole('button', { name: 'Discard changes' }))
  expect(screen.getByLabelText('Appearance')).toHaveProperty('value', 'light')
  await user.selectOptions(screen.getByLabelText('Appearance'), 'dark')
  fetchMock.mockResolvedValueOnce(response({ ...defaults, theme: 'dark', revision: 1 }))
  await user.click(screen.getByRole('button', { name: 'Save preferences' }))
  await screen.findByText('Saved to your account')
  expect(document.documentElement.dataset.theme).toBe('dark')
})

it('focuses conflicts, reloads the latest choices explicitly, and clears drafts when locked', async () => {
  const user = userEvent.setup()
  render(<Workspace controller={controller} />)
  await screen.findByLabelText('Appearance')
  await user.selectOptions(screen.getByLabelText('Display currency'), 'USD')
  fetchMock.mockResolvedValueOnce(response({}, 409))
  await user.click(screen.getByRole('button', { name: 'Save preferences' }))
  expect(document.activeElement).toBe(await screen.findByRole('alert'))
  expect(screen.getByLabelText('Display currency')).toHaveProperty('value', 'USD')
  expect(screen.queryByRole('button', { name: 'Save preferences' })).toBeNull()
  current = saved
  await user.click(screen.getByRole('button', { name: 'Reload saved settings' }))
  await waitFor(() => expect(document.documentElement.dataset.theme).toBe('dark'))
  expect(screen.getByLabelText('Amount privacy')).toHaveProperty('value', 'visible')
  fireEvent(window, new Event('offline'))
  expect(screen.queryByLabelText('Display currency')).toBeNull()
  expect(document.documentElement.dataset.theme).toBe('light')
  expect(JSON.stringify(controller.snapshot())).not.toContain('preferences')
})
