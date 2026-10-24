import { StrictMode } from 'react'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import axe from 'axe-core'
import Workspace from '../../workspace/src/Workspace'
import { AuthController } from '../../workspace/src/auth'

const preferences = () => ({ theme: 'light', display_currency: 'INR', amount_masked: true, revision: 0 })
const factor = '40000000-0000-4000-8000-000000000001'
const fetchMock = vi.fn<typeof fetch>()
function response(data: unknown, status = 200) { return new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store', Date: new Date().toUTCString() } }) }
function session() { return { status: 'authenticated', workspace_context: 'a'.repeat(64), expires_at: new Date(Date.now() + 28_800_000).toISOString(), idle_expires_at: new Date(Date.now() + 900_000).toISOString(), fresh_until: new Date(Date.now() + 300_000).toISOString(), factors: [factor], unverified_factors: [] } }
beforeEach(() => {
  document.cookie = 'trading_dev_csrf=synthetic-csrf-value-long-enough; Path=/'
  vi.stubGlobal('fetch', fetchMock); fetchMock.mockReset()
  fetchMock.mockImplementation(async path => path === '/api/v1/auth/bootstrap' ? response({ status: 'ready', recovery_email_enabled: false }) : response({}, 401))
})
afterEach(() => { vi.unstubAllGlobals(); document.cookie = 'trading_dev_csrf=; Max-Age=0; Path=/'; delete document.documentElement.dataset.theme })

it('has an accessible sign-in screen in Strict Mode without a protected-content flash', async () => {
  const { container } = render(<StrictMode><Workspace /></StrictMode>)
  expect(screen.queryByText('A fresh start.')).toBeNull()
  const heading = await screen.findByRole('heading', { name: 'Welcome to your workspace.' })
  expect(document.activeElement).toBe(heading)
  expect(screen.getByLabelText('Password').getAttribute('autocomplete')).toBe('current-password')
  expect(screen.queryByText('Forgot your password?')).toBeNull()
  expect((await axe.run(container, { rules: { 'color-contrast': { enabled: false } } })).violations).toEqual([])
})

it('supports password managers, paste, MFA enrollment, focus movement, and clearing secrets', async () => {
  const user = userEvent.setup()
  render(<Workspace />)
  await screen.findByLabelText('Email address')
  await user.type(screen.getByLabelText('Email address'), 'owner@example.invalid')
  await user.click(screen.getByLabelText('Password')); await user.paste('synthetic password')
  fetchMock.mockResolvedValueOnce(response({ status: 'mfa_required', factors: [factor], setup_key: 'JBSWY3DPEHPK3PXP' }))
  await user.click(screen.getByRole('button', { name: 'Continue securely' }))
  expect(await screen.findByLabelText(/Setup key/)).toBeTruthy()
  expect(document.activeElement).toBe(screen.getByRole('heading', { name: 'One more layer of security.' }))
  await user.click(screen.getByLabelText('6-digit authenticator code')); await user.paste('123456')
  fetchMock.mockResolvedValueOnce(response({ status: 'authenticated' })).mockResolvedValueOnce(response(session())).mockResolvedValueOnce(response(preferences()))
  await user.click(screen.getByRole('button', { name: 'Verify authenticator' }))
  await screen.findByRole('heading', { name: 'A fresh start.' })
  expect(screen.queryByDisplayValue('JBSWY3DPEHPK3PXP')).toBeNull()
  expect(screen.queryByText(/₹|AAPL|Accenture/)).toBeNull()
  expect(document.activeElement).toBe(screen.getByRole('heading', { name: 'A fresh start.' }))
})

it('switches themes in memory and does not use demo preferences', async () => {
  localStorage.setItem('portfolio.display.v1', JSON.stringify({ theme: 'dark', hidden: false }))
  const setItem = vi.spyOn(Storage.prototype, 'setItem')
  render(<Workspace />); await screen.findByLabelText('Email address')
  expect(document.documentElement.dataset.theme).toBe('light')
  await userEvent.click(screen.getByLabelText('Switch to dark mode'))
  expect(document.documentElement.dataset.theme).toBe('dark')
  expect(setItem).not.toHaveBeenCalled()
})

it('renders an accessible empty workspace and hides it immediately offline', async () => {
  fetchMock.mockImplementation(async path => path === '/api/v1/auth/bootstrap' ? response({ status: 'ready', recovery_email_enabled: false }) : path === '/api/v1/preferences' ? response(preferences()) : response(session()))
  const { container } = render(<Workspace />)
  await screen.findByRole('heading', { name: 'A fresh start.' })
  expect((await axe.run(container, { rules: { 'color-contrast': { enabled: false } } })).violations).toEqual([])
  fireEvent(window, new Event('offline'))
  expect(screen.queryByRole('heading', { name: 'A fresh start.' })).toBeNull()
  expect(screen.getByRole('heading', { name: 'You’re offline.' })).toBeTruthy()
})

it('requires revalidation after visibility changes and history restoration', async () => {
  fetchMock.mockImplementation(async path => path === '/api/v1/auth/bootstrap' ? response({ status: 'ready', recovery_email_enabled: false }) : path === '/api/v1/preferences' ? response(preferences()) : response(session()))
  render(<Workspace />); await screen.findByRole('heading', { name: 'A fresh start.' })
  const visibility = vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('hidden')
  fireEvent(document, new Event('visibilitychange'))
  expect(screen.queryByRole('heading', { name: 'A fresh start.' })).toBeNull()
  visibility.mockReturnValue('visible')
  fetchMock.mockResolvedValueOnce(response({ status: 'ready', recovery_email_enabled: false })).mockResolvedValueOnce(response({}, 401))
  fireEvent(document, new Event('visibilitychange'))
  await screen.findByRole('heading', { name: 'Welcome to your workspace.' })
  fireEvent(window, new Event('pagehide'))
  expect(screen.getByRole('heading', { name: 'Checking your session.' })).toBeTruthy()
  fireEvent(window, new Event('pageshow'))
  await waitFor(() => expect(screen.queryByRole('heading', { name: 'Checking your session.' })).toBeNull())
})

it('shows a non-enumerating recovery response, then requires MFA before a new password', async () => {
  const controller = new AuthController(), user = userEvent.setup()
  fetchMock.mockImplementation(async path => path === '/api/v1/auth/bootstrap' ? response({ status: 'ready', recovery_email_enabled: true }) : response({}, 401))
  render(<Workspace controller={controller} />)
  await user.click(await screen.findByRole('button', { name: 'Forgot your password?' }))
  await user.type(screen.getByLabelText('Account email'), 'owner@example.invalid')
  fetchMock.mockResolvedValueOnce(response({ status: 'recovery_requested' }, 202))
  await user.click(screen.getByRole('button', { name: 'Send recovery code' }))
  await screen.findByText(/If this address is eligible/)
  fetchMock.mockResolvedValueOnce(response({ status: 'mfa_required', factors: [factor] }))
  await act(() => controller.verifyRecovery('owner@example.invalid', '123456'))
  fetchMock.mockResolvedValueOnce(response({ status: 'password_required' }))
  await act(() => controller.verify(factor, '123456'))
  expect(screen.queryByRole('heading', { name: 'A fresh start.' })).toBeNull()
  await user.type(screen.getByLabelText('New password'), 'a synthetic password')
  await user.type(screen.getByLabelText('Confirm new password'), 'a different password')
  await user.click(screen.getByRole('button', { name: 'Change password' }))
  expect(screen.getByRole('alert').textContent).toContain('do not match')
  expect(document.activeElement).toBe(screen.getByLabelText('New password'))
})
