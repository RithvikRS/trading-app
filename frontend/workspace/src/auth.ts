// Only opaque cookies cross the session boundary. This module has no storage adapter.
import { parsePreferences } from './preferences'
import { authorizationTarget, parseConnection } from './indmoney'
import type { ConnectionAction, ConnectionState } from './indmoney'
import { ACCOUNT_PAGE_SIZE, accountCursor, parseAccountPage } from './accounts'
import type { AccountNavigation, AccountsState } from './accounts'
import type { DisplayPreferences, PreferenceSnapshot, PreferenceStatus } from './preferences'
import type { FinancePath } from './investments'
import type { BankSetupPath } from './bank-setup'
import type { BankMappingPath } from './bank-mappings'
export type Session = { status: 'authenticated'; workspace_context: string; expires_at: string; idle_expires_at: string; fresh_until: string; factors: string[]; unverified_factors: string[] }
export type Pending = { status: 'mfa_required'; factors: string[]; setup_key?: string }
export type Screen =
  | { kind: 'checking' }
  | { kind: 'login'; message?: string }
  | { kind: 'mfa'; pending: Pending; deadline: number }
  | { kind: 'recovery'; sent: boolean; message?: string }
  | { kind: 'password'; deadline: number }
  | { kind: 'workspace'; session: Session; deadline: number; preferences: PreferenceSnapshot; preferenceStatus: PreferenceStatus; accounts: AccountsState; connection?: ConnectionState }
  | { kind: 'blocked'; reason: 'offline' | 'unavailable' | 'forbidden' | 'limited' | 'context' | 'protocol' | 'signout'; retryAt?: number; notice?: string }

export type State = { screen: Screen; busy: boolean; recovery: boolean }
type Json = Record<string, unknown>
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/
const ids = (value: unknown): value is string[] => Array.isArray(value) && value.length <= 2 && value.every(id => typeof id === 'string' && uuid.test(id)) && new Set(value).size === value.length
const record = (value: unknown): value is Json => !!value && typeof value === 'object' && !Array.isArray(value)
const exact = (value: Json, keys: string[]) => Object.keys(value).every(key => keys.includes(key))
const invalid = () => new AuthError('protocol')
class PreferenceConflict extends Error {}
class ConnectionNotConfigured extends Error {}
export class FinancialRequestError extends Error {
  constructor(readonly conflict = false) { super('Saved evidence could not be verified. Reload before trying again.') }
}

export class AuthError extends Error {
  constructor(readonly reason: 'unauthorized' | 'offline' | 'unavailable' | 'forbidden' | 'limited' | 'context' | 'protocol', readonly retryAt?: number) { super('Authentication request failed.') }
}

function csrf(): string {
  const name = location.protocol === 'https:' ? '__Host-portfolio-csrf' : 'trading_dev_csrf'
  const found = document.cookie.split(';').map(part => part.trim()).filter(part => part.startsWith(`${name}=`))
  if (found.length !== 1) throw new AuthError('forbidden')
  const value = found[0]!.slice(name.length + 1)
  if (!/^[A-Za-z0-9_.=-]{16,1024}$/.test(value)) throw new AuthError('forbidden')
  return value
}

async function request(path: string, signal: AbortSignal, body?: Json, method?: 'PUT', workspaceContext?: string): Promise<{ data: Json; now: number }> {
  const started = performance.now()
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (path !== '/bootstrap') headers['X-CSRFToken'] = csrf()
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  const connector = path === '/connections/indmoney' || path.startsWith('/connections/indmoney/')
  const financial = path.startsWith('/finance/')
  if (path === '/preferences' || financial || connector) {
    if (typeof workspaceContext !== 'string' || !/^[0-9a-f]{64}$/.test(workspaceContext)) throw invalid()
    headers['X-Workspace-Context'] = workspaceContext
  }
  let response: Response
  try {
    response = await fetch(connector || financial ? `/api/v1${path}` : path === '/preferences' ? '/api/v1/preferences' : `/api/v1/auth${path}`, {
      method: method ?? (body === undefined ? 'GET' : 'POST'), headers,
      credentials: 'same-origin', mode: 'same-origin', redirect: 'error', cache: 'no-store',
      referrerPolicy: 'no-referrer', signal, body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch { throw new AuthError(navigator.onLine === false ? 'offline' : 'unavailable') }
  if (!response.ok) {
    void response.body?.cancel()
    if (connector && response.status === 404) throw new ConnectionNotConfigured()
    if (response.status === 401) throw new AuthError('unauthorized')
    if (response.status === 403) throw new AuthError('forbidden')
    if (response.status === 412) throw new AuthError('context')
    if (response.status === 409 && path === '/preferences') throw new PreferenceConflict()
    if (financial && [404, 409].includes(response.status)) throw new FinancialRequestError(true)
    if (response.status === 429) throw new AuthError('limited', Date.now() + 5_000)
    throw new AuthError('unavailable')
  }
  if (response.headers.get('content-type')?.split(';')[0] !== 'application/json' || response.headers.get('cache-control') !== 'no-store') throw invalid()
  // Stream a bounded body; never render server errors or unexpected response fields.
  const reader = response.body?.getReader()
  if (!reader) throw invalid()
  const chunks: Uint8Array[] = []
  let size = 0
  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      size += value.length
      if (size > (financial ? 256 * 1024 : 8192)) throw invalid()
      chunks.push(value)
    }
  } finally { await reader.cancel() }
  const bytes = new Uint8Array(size)
  let offset = 0
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length }
  let data: unknown
  try { data = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes)) } catch { throw invalid() }
  if (!record(data)) throw invalid()
  const server = Date.parse(response.headers.get('date') ?? '')
  if (!Number.isFinite(server)) throw invalid()
  // Include transport time and HTTP Date's one-second precision; expire conservatively.
  return { data, now: server + 1000 + performance.now() - started }
}

export function parseSession(data: Json, now: number): Session {
  if (!exact(data, ['status', 'workspace_context', 'expires_at', 'idle_expires_at', 'fresh_until', 'factors', 'unverified_factors']) || data.status !== 'authenticated' || typeof data.workspace_context !== 'string' || !/^[0-9a-f]{64}$/.test(data.workspace_context) || !ids(data.factors) || !data.factors.length || !ids(data.unverified_factors)) throw invalid()
  for (const key of ['expires_at', 'idle_expires_at', 'fresh_until']) {
    if (typeof data[key] !== 'string' || !/^\d{4}-\d\d-\d\dT[\d:.]+(?:Z|\+00:00)$/.test(data[key]) || !Number.isFinite(Date.parse(data[key]))) throw invalid()
  }
  const session = data as Session
  const remaining = Math.min(Date.parse(session.expires_at), Date.parse(session.idle_expires_at)) - now
  if (remaining <= 0 || remaining > 15 * 60_000 || Date.parse(session.expires_at) - now > 8 * 60 * 60_000) throw new AuthError('unauthorized')
  return session
}

function pending(data: Json): Pending {
  if (data.status !== 'mfa_required' || !exact(data, ['status', 'factors', 'setup_key']) || !ids(data.factors) || !data.factors.length || (data.setup_key !== undefined && (typeof data.setup_key !== 'string' || !/^[A-Z2-7]{16,128}$/.test(data.setup_key)))) throw invalid()
  return data as Pending
}

export class AuthController {
  constructor(private readonly navigate: (url: string) => void = url => window.location.assign(url)) {}
  private state: State = { screen: { kind: 'checking' }, busy: false, recovery: false }
  private listeners = new Set<() => void>()
  private generation = 0
  private controller?: AbortController
  private pendingDeadline = 0
  private timer?: ReturnType<typeof setInterval>
  private channel?: BroadcastChannel
  private signoutAll = false
  private lastCheck = 0
  subscribe = (listener: () => void) => { this.listeners.add(listener); return () => { this.listeners.delete(listener) } }
  snapshot = () => this.state
  private set(screen: Screen, busy = false) { this.state = { ...this.state, screen, busy }; this.listeners.forEach(listener => listener()) }
  private cancel() { this.generation++; this.controller?.abort(); this.controller = undefined }
  private fail(error: unknown, message = 'Your session ended. Sign in again.') {
    const failure = error instanceof AuthError ? error : invalid()
    this.set(failure.reason === 'unauthorized' ? { kind: 'login', message } : { kind: 'blocked', reason: failure.reason, retryAt: failure.retryAt })
  }
  private async run(action: (signal: AbortSignal, current: () => boolean, latest: () => boolean) => Promise<void>) {
    if (this.state.busy) return
    const generation = ++this.generation
    const controller = new AbortController()
    this.controller = controller
    this.set(this.state.screen, true)
    const timeout = setTimeout(() => controller.abort(), 20_000)
    const latest = () => generation === this.generation
    const current = () => latest() && !controller.signal.aborted
    try { await action(controller.signal, current, latest) }
    catch (error) { if (generation === this.generation) this.fail(error) }
    finally {
      clearTimeout(timeout)
      if (generation === this.generation) { this.controller = undefined; this.set(this.state.screen) }
    }
  }
  private activate(data: Json, now: number, loaded?: PreferenceSnapshot) {
    const session = parseSession(data, now)
    const previous = this.state.screen
    if (previous.kind === 'workspace' && previous.session.workspace_context !== session.workspace_context) throw new AuthError('context')
    const preferences = loaded ?? (previous.kind === 'workspace' ? previous.preferences : undefined)
    if (!preferences) throw invalid()
    this.lastCheck = performance.now()
    this.set({ kind: 'workspace', session, preferences, accounts: previous.kind === 'workspace' ? previous.accounts : { kind: 'idle' }, connection: previous.kind === 'workspace' ? previous.connection : undefined, preferenceStatus: loaded ? 'idle' : previous.kind === 'workspace' ? previous.preferenceStatus : 'idle', deadline: performance.now() + Math.min(Date.parse(session.expires_at), Date.parse(session.idle_expires_at)) - now })
  }
  private async openWorkspace(signal: AbortSignal, current: () => boolean) {
    const session = await request('/session', signal)
    if (!current()) return
    const checked = parseSession(session.data, session.now)
    const received = performance.now()
    const result = await request('/preferences', signal, undefined, undefined, checked.workspace_context)
    if (current()) this.activate(session.data, session.now + performance.now() - received, parsePreferences(result.data))
  }
  start() {
    this.cancel()
    this.set({ kind: 'checking' })
    if (typeof BroadcastChannel !== 'undefined') {
      this.channel = new BroadcastChannel('portfolio-session-events')
      this.channel.onmessage = event => { if (event.data === 'locked') this.lock('Your session changed in another tab. Sign in again.') }
    }
    this.timer = setInterval(() => {
      const screen = this.state.screen
      if ('deadline' in screen && performance.now() >= screen.deadline) void this.logout(false, 'Your session expired. Sign in again.')
      else if (screen.kind === 'workspace' && performance.now() - this.lastCheck >= 60_000 && document.visibilityState === 'visible') void this.check()
    }, 1000)
    void this.bootstrap()
    return () => { this.cancel(); clearInterval(this.timer); this.channel?.close(); this.set({ kind: 'checking' }) }
  }
  lock(message = 'Sign in to continue.') { this.cancel(); this.set({ kind: 'login', message }) }
  suspend = () => { this.cancel(); this.set({ kind: 'checking' }) }
  resume = () => { if (this.state.screen.kind === 'checking') void this.bootstrap() }
  offline = () => { this.cancel(); this.set({ kind: 'blocked', reason: 'offline' }) }
  bootstrap = async () => {
    if (this.state.busy) return
    this.set({ kind: 'checking' })
    await this.run(async (signal, current, latest) => {
      const { data } = await request('/bootstrap', signal)
      if (!current()) return
      if (data.status !== 'ready' || typeof data.recovery_email_enabled !== 'boolean' || !exact(data, ['status', 'recovery_email_enabled'])) throw invalid()
      this.state = { ...this.state, recovery: data.recovery_email_enabled }
      try {
        await this.openWorkspace(signal, current)
      } catch (error) { if (latest()) this.fail(error, 'Sign in to your private workspace.') }
    })
  }
  login = (email: string, password: string) => {
    this.pendingDeadline = performance.now() + 5 * 60_000
    return this.run(async (signal, current) => {
      this.channel?.postMessage('locked')
      const { data } = await request('/login', signal, { email, password })
      if (current()) this.set({ kind: 'mfa', pending: pending(data), deadline: this.pendingDeadline })
    })
  }
  verify = (factor_id: string, code: string) => this.run(async (signal, current) => {
    const { data } = await request('/mfa/verify', signal, { factor_id, code })
    if (!current()) return
    if (data.status === 'password_required' && exact(data, ['status'])) this.set({ kind: 'password', deadline: this.pendingDeadline })
    else if (data.status === 'authenticated' && exact(data, ['status'])) {
      this.set({ kind: 'checking' }, true)
      await this.openWorkspace(signal, current)
    } else throw invalid()
  })
  check = () => this.run(async (signal, current) => {
    const result = await request('/session', signal)
    if (current()) this.activate(result.data, result.now)
  })
  activity = () => this.run(async (signal, current) => {
    const result = await request('/session/activity', signal, {})
    if (current()) this.activate(result.data, result.now)
  })
  loadAccounts = (direction: AccountNavigation = 'first') => {
    const previous = this.state.screen
    if (previous.kind !== 'workspace') return Promise.resolve()
    const cursor = accountCursor(previous.accounts, direction)
    if (!cursor) return Promise.resolve()
    return this.run(async (signal, current, latest) => {
      if (performance.now() >= previous.deadline) throw new AuthError('unauthorized')
      this.set({ ...previous, accounts: { kind: 'loading', cursor } }, true)
      try {
        const result = await request('/finance/accounts/query', signal, { limit: ACCOUNT_PAGE_SIZE, after: cursor.after }, undefined, previous.session.workspace_context)
        if (!current()) { if (latest()) throw new AuthError('unavailable'); return }
        if (performance.now() >= previous.deadline) throw new AuthError('unauthorized')
        const page = parseAccountPage(result.data, cursor.after)
        this.set({ ...previous, accounts: { kind: 'ready', cursor, page } })
      } catch (error) {
        if (!latest()) return
        if (performance.now() >= previous.deadline) throw new AuthError('unauthorized')
        if (error instanceof AuthError && ['unavailable', 'limited'].includes(error.reason)) {
          this.set({ ...previous, accounts: { kind: 'failed', cursor, limited: error.reason === 'limited' } })
        } else throw error
      }
    })
  }
  finance = async <T,>(path: FinancePath | BankSetupPath | BankMappingPath, body: Json, parse: (value: unknown) => T): Promise<T | undefined> => {
    const previous = this.state.screen
    if (previous.kind !== 'workspace' || this.state.busy) return undefined
    let result: T | undefined, failure: FinancialRequestError | undefined
    await this.run(async (signal, current, latest) => {
      if (performance.now() >= previous.deadline) throw new AuthError('unauthorized')
      try {
        const response = await request(`/finance${path}`, signal, body, undefined, previous.session.workspace_context)
        if (!current()) { if (latest()) throw new AuthError('unavailable'); return }
        if (performance.now() >= previous.deadline) throw new AuthError('unauthorized')
        result = parse(response.data)
      } catch (error) {
        if (!latest()) return
        if (performance.now() >= previous.deadline) throw new AuthError('unauthorized')
        if (error instanceof FinancialRequestError || error instanceof AuthError && ['unavailable', 'limited'].includes(error.reason)) failure = new FinancialRequestError(error instanceof FinancialRequestError)
        else throw error
      }
    })
    if (failure) throw failure
    return this.state.screen.kind === 'workspace' && this.state.screen.session.workspace_context === previous.session.workspace_context ? result : undefined
  }
  connection = (action: ConnectionAction) => {
    const previous = this.state.screen
    if (previous.kind !== 'workspace') return Promise.resolve()
    return this.run(async (signal, current, latest) => {
      if (performance.now() >= previous.deadline) throw new AuthError('unauthorized')
      this.set({ ...previous, connection: { kind: 'loading' } }, true)
      try {
        const path = '/connections/indmoney' + (action === 'status' ? '' : `/${action}`)
        const result = await request(path, signal, action === 'status' ? undefined : {}, undefined, previous.session.workspace_context)
        if (!current()) { if (latest()) throw new AuthError('unavailable'); return }
        if (performance.now() >= previous.deadline) throw new AuthError('unauthorized')
        if (action === 'authorize') { this.navigate(authorizationTarget(result.data)); return }
        if (action === 'status') { this.set({ ...previous, connection: { kind: 'ready', value: parseConnection(result.data) } }); return }
        if (action === 'disconnect') {
          if (!exact(result.data, ['status', 'provider_cleanup']) || result.data.status !== 'disconnected' || !['confirmed', 'unavailable', 'not_needed'].includes(String(result.data.provider_cleanup))) throw invalid()
          this.set({ ...previous, connection: { kind: 'ready', value: { status: 'disconnected', can_complete: false, expires_at: null, financial_access_enabled: false }, cleanup: result.data.provider_cleanup as 'confirmed' | 'unavailable' | 'not_needed' } }); return
        }
        if (!exact(result.data, ['status']) || result.data.status !== 'authorized') throw invalid()
        const status = await request('/connections/indmoney', signal, undefined, undefined, previous.session.workspace_context)
        if (!current()) { if (latest()) throw new AuthError('unavailable'); return }
        if (performance.now() >= previous.deadline) throw new AuthError('unauthorized')
        this.set({ ...previous, connection: { kind: 'ready', value: parseConnection(status.data) } })
      } catch (error) {
        if (!latest()) return
        if (performance.now() >= previous.deadline) throw new AuthError('unauthorized')
        if (error instanceof ConnectionNotConfigured) this.set({ ...previous, connection: { kind: 'unconfigured' } })
        else if (error instanceof AuthError && ['unavailable', 'limited'].includes(error.reason)) this.set({ ...previous, connection: { kind: 'failed' } })
        else throw error
      }
    })
  }
  reloadPreferences = () => {
    const previous = this.state.screen
    if (previous.kind !== 'workspace') return Promise.resolve()
    return this.run(async (signal, current) => {
      if (performance.now() >= previous.deadline) throw new AuthError('unauthorized')
      const result = await request('/preferences', signal, undefined, undefined, previous.session.workspace_context)
      if (current() && this.state.screen.kind === 'workspace') {
        if (performance.now() >= previous.deadline) throw new AuthError('unauthorized')
        this.set({ ...this.state.screen, preferences: parsePreferences(result.data), preferenceStatus: 'idle' })
      }
    })
  }
  savePreferences = (changes: DisplayPreferences) => {
    const previous = this.state.screen
    if (previous.kind !== 'workspace' || previous.preferenceStatus === 'conflict') return Promise.resolve()
    return this.run(async (signal, current, latest) => {
      this.set({ ...previous, preferenceStatus: 'saving' }, true)
      try {
        if (performance.now() >= previous.deadline) throw new AuthError('unauthorized')
        const result = await request('/preferences', signal, { ...changes, revision: previous.preferences.revision }, 'PUT', previous.session.workspace_context)
        if (!current()) return
        if (performance.now() >= previous.deadline) throw new AuthError('unauthorized')
        const preferences = parsePreferences(result.data)
        if (preferences.revision !== previous.preferences.revision + 1 || preferences.theme !== changes.theme || preferences.display_currency !== changes.display_currency || preferences.amount_masked !== changes.amount_masked) throw invalid()
        this.set({ ...previous, preferences, preferenceStatus: 'saved' })
      } catch (error) {
        if (!latest()) return
        if (error instanceof PreferenceConflict && performance.now() < previous.deadline) this.set({ ...previous, preferenceStatus: 'conflict' })
        else {
          this.fail(error, 'Your session ended. The save was not confirmed; saved settings will load after sign-in.')
          if (this.state.screen.kind === 'blocked') this.set({ ...this.state.screen, notice: 'The save was not confirmed. Check your connection and reload saved settings before trying again.' })
        }
      }
    })
  }
  logout = async (all = false, message?: string) => {
    this.signoutAll = all
    this.cancel()
    this.set({ kind: 'checking' })
    this.channel?.postMessage('locked')
    await this.run(async (signal, current, latest) => {
      try {
        const { data } = await request(all ? '/revoke-all' : '/logout', signal, {})
        if (!current()) return
        if (data.status !== 'signed_out' || !['complete', 'unavailable'].includes(String(data.provider_cleanup)) || !exact(data, ['status', 'provider_cleanup'])) throw invalid()
        this.set({ kind: 'login', message: data.provider_cleanup === 'complete' ? message ?? 'Signed out. Your workspace is locked.' : 'Workspace signed out. Provider cleanup is unavailable; contact the operator if needed.' })
      } catch (error) {
        if (!latest()) return
        if (error instanceof AuthError && error.reason === 'unauthorized') this.set({ kind: 'login', message: message ?? 'This session is no longer active.' })
        else this.set({ kind: 'blocked', reason: 'signout' })
      }
    })
  }
  retryLogout = () => this.logout(this.signoutAll)
  recovery = () => { if (this.state.recovery && !this.state.busy) this.set({ kind: 'recovery', sent: false }) }
  requestRecovery = (email: string) => this.run(async (signal, current) => {
    const { data } = await request('/recovery/request', signal, { email })
    if (data.status !== 'recovery_requested' || !exact(data, ['status'])) throw invalid()
    if (current()) this.set({ kind: 'recovery', sent: true, message: 'If this address is eligible, a code has been sent. You will also need your authenticator.' })
  })
  verifyRecovery = (email: string, code: string) => {
    this.pendingDeadline = performance.now() + 5 * 60_000
    return this.run(async (signal, current) => {
      this.channel?.postMessage('locked')
      const { data } = await request('/recovery/verify', signal, { email, code })
      if (current()) this.set({ kind: 'mfa', pending: pending(data), deadline: this.pendingDeadline })
    })
  }
  password = (password: string) => this.run(async (signal, current) => {
    const { data } = await request('/recovery/password', signal, { password })
    if (data.status !== 'sign_in_required' || !exact(data, ['status'])) throw invalid()
    if (current()) { this.channel?.postMessage('locked'); this.set({ kind: 'login', message: 'Password changed and sessions revoked. Sign in with your new password.' }) }
  })
}
