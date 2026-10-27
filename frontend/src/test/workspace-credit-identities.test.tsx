import { StrictMode } from 'react'
import { act, fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import axe from 'axe-core'
import Workspace from '../../workspace/src/Workspace'
import { AuthController } from '../../workspace/src/auth'
import { creditAccount, creditAccountInspection, creditAccounts, creditMappingHistory, creditSource, creditSources, creditSourceState } from '../../workspace/src/credit-identities'
import type { CreditAccount, CreditSource } from '../../workspace/src/credit-identities'

const id = (n: number) => `79000000-0000-4000-8000-${String(n).padStart(12, '0')}`
const active: CreditAccount = { id: id(1), issuer: 'hdfc', billing_currency: 'INR', label: 'Everyday card', revision: 1, state: 'active' }
const archived: CreditAccount = { ...active, id: id(2), label: 'Earlier card', revision: 2, state: 'archived' }
const source: CreditSource = { id: id(10), family: 'hdfc_credit_statement', mapping_revision: 3, account_id: active.id, state: 'mapped' }
const unlinked: CreditSource = { ...source, id: id(11), mapping_revision: 2, account_id: null, state: 'unmapped' }
const never: CreditSource = { ...source, id: id(12), mapping_revision: null, account_id: null, state: 'unmapped' }
const archivedSource: CreditSource = { ...source, id: id(13), mapping_revision: 1, account_id: archived.id, state: 'archived' }
const mapping = (revision: number, changes: Record<string, unknown> = {}) => ({ source_id: source.id, revision, previous_revision: revision > 1 ? revision - 1 : null, account_id: revision === 2 ? null : revision === 1 ? archived.id : active.id, reason: revision === 1 ? 'initial' : revision === 2 ? 'unlinked' : 'correction', is_latest_revision: revision === 3, account_state: revision === 2 ? null : revision === 1 ? 'archived' : 'active', ...changes })
const mappings = () => [mapping(3), mapping(2), mapping(1)]
const sourceList = () => [source, unlinked, never, archivedSource]
const session = () => ({ status: 'authenticated', workspace_context: 'c'.repeat(64), expires_at: new Date(Date.now() + 28_800_000).toISOString(), idle_expires_at: new Date(Date.now() + 900_000).toISOString(), fresh_until: new Date(Date.now() + 300_000).toISOString(), factors: [id(99)], unverified_factors: [] })
const response = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store', Date: new Date().toUTCString() } })
const fetchMock = vi.fn<typeof fetch>()
let auth: AuthController, masked: boolean, currency: string, theme: string, preferenceRevision: number
beforeEach(() => {
  masked = false; currency = 'INR'; theme = 'light'; preferenceRevision = 1
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
    if (path === '/api/v1/finance/credit/accounts/query') return response({ items: [active, archived], next_after: null })
    if (path === '/api/v1/finance/credit/accounts/inspect') return response(JSON.parse(String(options?.body)).id === archived.id ? archived : active)
    if (path === '/api/v1/finance/credit/sources/query') return response({ items: sourceList(), next_after: null })
    if (path === '/api/v1/finance/credit/sources/mappings/history') {
      const body = JSON.parse(String(options?.body))
      return response({ items: body.id === never.id ? [] : mappings().map(item => ({ ...item, source_id: body.id })), next_before: null })
    }
    return response({}, 404)
  })
})
afterEach(() => { auth.lock(); vi.unstubAllGlobals(); document.cookie = 'trading_dev_csrf=; Max-Age=0; Path=/'; delete document.documentElement.dataset.theme })
function override(path: string, handler: (body: Record<string, unknown>) => unknown, status = 200) { const previous = fetchMock.getMockImplementation()!; fetchMock.mockImplementation((url, options) => url === path ? Promise.resolve(response(handler(JSON.parse(String(options?.body))), status)) : previous(url, options)) }
async function openCards(strict = false) {
  const workspace = <Workspace controller={auth} />; render(strict ? <StrictMode>{workspace}</StrictMode> : workspace)
  await screen.findByRole('heading', { name: 'A fresh start.' })
  fireEvent.click(within(screen.getByRole('navigation', { name: 'Workspace navigation' })).getByRole('button', { name: 'Credit Cards' }))
  await screen.findByRole('heading', { name: 'Saved billing accounts' })
}
async function openSources() { await openCards(); fireEvent.click(screen.getByRole('button', { name: 'Source directory' })); await screen.findByRole('heading', { name: 'Saved sources' }) }
async function openHistory() { await openSources(); fireEvent.click(screen.getByRole('button', { name: `Link history for source ${source.id}` })); await screen.findByRole('heading', { name: 'Source link history' }) }
const creditCalls = () => fetchMock.mock.calls.filter(([path]) => String(path).includes('/finance/credit/'))

it('preserves safe HDFC INR active and archived identities without financial values', () => {
  expect(creditAccounts({ items: [active, archived], next_after: null }).items).toEqual([active, archived])
  expect(creditAccountInspection({ ...active, revision: 2, state: 'archived' }, active).state).toBe('archived')
  expect(creditAccountInspection(archived, archived.id)).toEqual(archived)
})
it.each([{ issuer: 'sbi' }, { billing_currency: 'USD' }, { label: 'Card 1234' }, { label: 'Bad\nlabel' }, { label: '' }, { label: 'a'.repeat(65) }, { id: 'BAD' }, { id: '79000000-0000-4000-000000000001' }, { id: '00000000-0000-0000-0000-000000000000' }, { revision: 0 }, { revision: '1' }, { revision: 9007199254740992 }, { state: 'deleted' }, { balance: '100.00' }])('rejects private or malformed credit identity fields %#', change => expect(() => creditAccount({ ...active, ...change })).toThrow())
it('rejects missing fields, changed selected identities and regressed same-revision payloads', () => {
  const { state: _state, ...missing } = active
  expect(() => creditAccount(missing)).toThrow()
  expect(() => creditAccountInspection(archived, active)).toThrow()
  expect(() => creditAccountInspection({ ...archived, revision: 1 }, archived)).toThrow()
  expect(() => creditAccountInspection({ ...active, label: 'Different' }, active)).toThrow()
  expect(() => creditAccountInspection({ ...active, state: 'archived' }, active)).toThrow()
})
it('distinguishes never linked, explicit unlink, mapped and archived targets', () => {
  expect(sourceList().map(creditSourceState)).toEqual(['Linked', 'Unlinked', 'Never linked', 'Linked to archived account'])
  expect(creditSources({ items: sourceList(), next_after: null }).items).toEqual(sourceList())
  expect(creditMappingHistory({ items: [], next_before: null }, never).items).toEqual([])
})
it.each([{ family: 'bank_statement' }, { state: 'active' }, { account_id: null }, { mapping_revision: null }, { mapping_revision: 0 }, { account_id: 'bad' }, { mapping_revision: 1.2 }, { card_number: 'private' }])('rejects inconsistent source binding %#', change => expect(() => creditSource({ ...source, ...change })).toThrow())
it('validates every directory row and exact bounded continuations', () => {
  const items = Array.from({ length: 25 }, (_, index) => ({ ...active, id: id(100 + index) }))
  expect(creditAccounts({ items, next_after: id(124) }).next_after).toBe(id(124))
  for (const value of [{ items: [active, active], next_after: null }, { items: [archived, active], next_after: null }, { items: [active], next_after: active.id }, { items, next_after: id(125) }, { items: [...items, { ...active, id: id(125) }], next_after: null }, { items: [active], next_after: null, raw: 'private' }]) expect(() => creditAccounts(value)).toThrow()
  expect(() => creditAccounts({ items: [active], next_after: null }, active.id)).toThrow()
  expect(() => creditSources({ items: [source, { ...unlinked, mapping_revision: 'bad' }], next_after: null })).toThrow()
})
it('keeps immutable mappings, independent observed lifecycle and newer link decisions', () => {
  expect(creditMappingHistory({ items: mappings(), next_before: null }, source).items).toEqual(mappings())
  const newer = [mapping(4, { is_latest_revision: true, account_id: archived.id, account_state: 'active' }), ...mappings().map(item => ({ ...item, is_latest_revision: false }))]
  expect(creditMappingHistory({ items: newer, next_before: null }, source).items).toEqual(newer)
  expect(creditMappingHistory({ items: [mapping(3, { account_state: 'archived' }), mapping(2), mapping(1)], next_before: null }, source).items[0]?.account_state).toBe('archived')
})
it.each([{ source_id: id(99) }, { revision: 0 }, { revision: 9007199254740992 }, { previous_revision: 1 }, { reason: 'initial' }, { is_latest_revision: false }, { is_latest_revision: 'true' }, { account_id: archived.id }, { account_state: null }, { amount: '99' }])('rejects changed mapping identity, history floor or private payload %#', change => expect(() => creditMappingHistory({ items: [mapping(3, change), mapping(2), mapping(1)], next_before: null }, source)).toThrow())
it('rejects empty known history, false exhaustion, gaps, duplicates and malformed predecessors', () => {
  expect(() => creditMappingHistory({ items: [], next_before: null }, source, null, null)).toThrow()
  expect(() => creditMappingHistory({ items: mappings(), next_before: null }, source, null, 2)).toThrow()
  for (const items of [[], [mapping(2), mapping(1)], [mapping(3), mapping(1)], [mapping(3), mapping(2), mapping(2)], [mapping(3)], [mapping(3), mapping(2, { account_state: 'active' }), mapping(1)], [mapping(3), mapping(2), mapping(1, { previous_revision: 1 })]]) expect(() => creditMappingHistory({ items, next_before: null }, source)).toThrow()
})
it('binds history continuation and retains only one page with its original source floor', () => {
  const items = Array.from({ length: 25 }, (_, i) => mapping(30 - i, { is_latest_revision: i === 0 }))
  const root = { ...source, mapping_revision: 30 }
  expect(creditMappingHistory({ items, next_before: 6 }, root).next_before).toBe(6)
  const older = Array.from({ length: 5 }, (_, i) => mapping(5 - i, { is_latest_revision: false }))
  expect(creditMappingHistory({ items: older, next_before: null }, root, 6).items).toEqual(older)
  for (const value of [{ items: older.slice(1), next_before: null }, { items: [], next_before: null }, { items: older.map((v, i) => ({ ...v, is_latest_revision: i === 0 })), next_before: null }, { items: older, next_before: 1 }]) expect(() => creditMappingHistory(value, root, 6)).toThrow()
  expect(() => creditMappingHistory({ items, next_before: 7 }, root)).toThrow()
  expect(() => creditMappingHistory({ items, next_before: null }, root)).toThrow()
})
it('accepts new mapping history for a formerly never-linked source without inventing a prior link', () => {
  expect(creditMappingHistory({ items: [mapping(1, { source_id: never.id, is_latest_revision: true })], next_before: null }, never).items).toHaveLength(1)
})
it('opens only the credit directory, explicitly inspects accounts and preserves archived identities', async () => {
  await openCards(true)
  expect(creditCalls()).toHaveLength(1)
  expect(creditCalls()[0]?.[1]).toMatchObject({ method: 'POST', credentials: 'same-origin', mode: 'same-origin', cache: 'no-store', redirect: 'error', referrerPolicy: 'no-referrer', headers: expect.objectContaining({ 'X-Workspace-Context': 'c'.repeat(64), 'X-CSRFToken': 'synthetic-csrf-value-long-enough' }) })
  fireEvent.click(screen.getByRole('button', { name: 'Inspect account Earlier card' }))
  await screen.findByRole('heading', { name: 'Billing account identity' }); expect(screen.getByText('Archived')).toBeTruthy()
  expect(creditCalls().at(-1)?.[1]?.body).toBe(JSON.stringify({ id: archived.id }))
  fireEvent.click(screen.getByRole('button', { name: 'All billing accounts' })); await screen.findByRole('heading', { name: 'Saved billing accounts' })
  expect(creditCalls().at(-1)?.[0]).toBe('/api/v1/finance/credit/accounts/query')
})
it('shows owner-wide source states without claiming account-filtered coverage', async () => {
  await openSources()
  for (const name of ['Linked', 'Unlinked', 'Never linked', 'Linked to archived account']) expect(screen.getByText(name)).toBeTruthy()
  expect(screen.getByText(/including unlinked sources and links to other billing accounts/)).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: `Link history for source ${never.id}` }))
  await screen.findByText('This source has no saved link history.')
})
it('inspects exact source revisions and re-reads a historical target account', async () => {
  await openHistory()
  expect(screen.getByRole('heading', { name: 'Revision 2 · Source unlinked' })).toBeTruthy()
  expect(screen.getByText('None — unlinked')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: 'Inspect account from link revision 1' }))
  await screen.findByRole('heading', { name: 'Earlier card' })
  expect(creditCalls().at(-1)?.[1]?.body).toBe(JSON.stringify({ id: archived.id }))
})
it('pages accounts with explicit previous, next and first reads without cached identities', async () => {
  const items = Array.from({ length: 25 }, (_, i) => ({ ...active, id: id(100 + i), label: `Card ${String.fromCharCode(65 + i)}` }))
  override('/api/v1/finance/credit/accounts/query', body => body.after ? { items: [{ ...archived, id: id(125) }], next_after: null } : { items, next_after: id(124) })
  await openCards(); fireEvent.click(screen.getByRole('button', { name: 'Next account page' })); await screen.findByText('Account page 2 · 1 shown')
  expect(creditCalls().at(-1)?.[1]?.body).toBe(JSON.stringify({ limit: 25, after: id(124) }))
  fireEvent.click(screen.getByRole('button', { name: 'Previous account page' })); await screen.findByText('Account page 1 · 25 shown')
  expect(creditCalls().at(-1)?.[1]?.body).toBe(JSON.stringify({ limit: 25, after: null }))
})
it('preserves an empty later source page and can re-read the first page', async () => {
  const items = Array.from({ length: 25 }, (_, i) => ({ ...never, id: id(100 + i) }))
  override('/api/v1/finance/credit/sources/query', body => body.after ? { items: [], next_after: null } : { items, next_after: id(124) })
  await openSources(); fireEvent.click(screen.getByRole('button', { name: 'Next source page' })); await screen.findByText('Source page 2 · 0 shown')
  expect(screen.getByText(/No saved sources on this page/)).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: 'First source page' })); await screen.findByText('Source page 1 · 25 shown')
})
it('pages descending link history and refreshes the exact current page', async () => {
  override('/api/v1/finance/credit/sources/mappings/history', body => body.before === 6 ? { items: Array.from({ length: 5 }, (_, i) => mapping(5 - i, { is_latest_revision: false })), next_before: null } : { items: Array.from({ length: 25 }, (_, i) => mapping(30 - i, { is_latest_revision: i === 0 })), next_before: 6 })
  await openHistory(); fireEvent.click(screen.getByRole('button', { name: 'Earlier link revisions' })); await screen.findByRole('heading', { name: 'Revision 1 · Initial link' })
  expect(screen.queryByRole('heading', { name: 'Revision 30 · Link corrected' })).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'Refresh link history' })); await screen.findByRole('heading', { name: 'Revision 1 · Initial link' })
  expect(creditCalls().at(-1)?.[1]?.body).toBe(JSON.stringify({ id: source.id, limit: 25, before: 6 }))
})
it.each([404, 409, 429, 503])('clears failed nested context and reloads a fresh account directory for status %i', async status => {
  await openHistory(); override('/api/v1/finance/credit/sources/mappings/history', () => ({}), status)
  fireEvent.click(screen.getByRole('button', { name: 'Refresh link history' })); await screen.findByText('Credit identities could not be verified.')
  expect(screen.queryByText(source.id)).toBeNull(); expect(screen.queryByRole('heading', { name: 'Revision 3 · Link corrected' })).toBeNull()
  expect(auth.snapshot().screen.kind).toBe('workspace')
  fireEvent.click(screen.getByRole('button', { name: 'Reload credit accounts' })); await screen.findByRole('heading', { name: 'Saved billing accounts' })
  expect(creditCalls().at(-1)?.[0]).toBe('/api/v1/finance/credit/accounts/query')
})
it('rejects malicious extra data before any directory values render', async () => {
  override('/api/v1/finance/credit/accounts/query', () => ({ items: [active, { ...archived, raw: '<script>private</script>' }], next_after: null }))
  render(<Workspace controller={auth} />); await screen.findByRole('heading', { name: 'A fresh start.' })
  fireEvent.click(within(screen.getByRole('navigation', { name: 'Workspace navigation' })).getByRole('button', { name: 'Credit Cards' }))
  await screen.findByRole('heading', { name: 'Unable to verify this response.' })
  expect(screen.queryByText(active.label)).toBeNull(); expect(document.body.textContent).not.toContain('<script>private</script>')
})
it('blocks a changed selected account or regressed history before rendering it', async () => {
  await openCards(); override('/api/v1/finance/credit/accounts/inspect', () => archived)
  fireEvent.click(screen.getByRole('button', { name: 'Inspect account Everyday card' }))
  await screen.findByRole('heading', { name: 'Unable to verify this response.' })
  expect(screen.queryByText('Billing account identity')).toBeNull()
})
it.each([401, 403, 412])('locks protected credit content on boundary status %i', async status => {
  await openSources(); override('/api/v1/finance/credit/sources/query', () => ({}), status)
  fireEvent.click(screen.getByRole('button', { name: 'Refresh sources' }))
  await vi.waitFor(() => expect(auth.snapshot().screen.kind).not.toBe('workspace'))
  expect(screen.queryByText('Saved sources')).toBeNull()
})
it('discards late source results after navigation away and reopening', async () => {
  await openCards(); const previous = fetchMock.getMockImplementation()!; let resolve!: (value: Response) => void
  fetchMock.mockImplementation((path, options) => path === '/api/v1/finance/credit/sources/query' ? new Promise(result => { resolve = result }) : previous(path, options))
  fireEvent.click(screen.getByRole('button', { name: 'Source directory' })); await vi.waitFor(() => expect(resolve).toBeTypeOf('function'))
  fireEvent.click(within(screen.getByRole('navigation', { name: 'Workspace navigation' })).getByRole('button', { name: 'Overview' }))
  await act(async () => resolve(response({ items: sourceList(), next_after: null })))
  expect(screen.queryByText('Saved sources')).toBeNull()
  fetchMock.mockImplementation(previous)
  fireEvent.click(within(screen.getByRole('navigation', { name: 'Workspace navigation' })).getByRole('button', { name: 'Credit Cards' }))
  await screen.findByRole('heading', { name: 'Saved billing accounts' }); expect(screen.queryByText('Saved sources')).toBeNull()
})
it('clears identifiers immediately at sign-out and rejects a late identity reply', async () => {
  await openCards(); const previous = fetchMock.getMockImplementation()!; let resolve!: (value: Response) => void
  fetchMock.mockImplementation((path, options) => path === '/api/v1/finance/credit/accounts/inspect' ? new Promise(result => { resolve = result }) : previous(path, options))
  fireEvent.click(screen.getByRole('button', { name: 'Inspect account Everyday card' })); await vi.waitFor(() => expect(resolve).toBeTypeOf('function'))
  fireEvent.click(screen.getByRole('button', { name: 'Sign out here' })); await act(async () => resolve(response(active)))
  await screen.findByRole('heading', { name: 'Welcome to your workspace.' }); expect(screen.queryByText(active.label)).toBeNull()
})
it.each(['light', 'dark'])('uses keyboard focus and accessible semantics in %s with no browser persistence', async appearance => {
  theme = appearance; masked = true; currency = 'USD'; await openCards()
  expect(document.activeElement).toBe(screen.getByRole('heading', { name: 'Your credit accounts' }))
  const user = userEvent.setup(); screen.getByRole('button', { name: 'Inspect account Everyday card' }).focus(); await user.keyboard('{Enter}')
  await screen.findByRole('heading', { name: 'Billing account identity' })
  expect(document.activeElement).toBe(screen.getByRole('heading', { name: 'Everyday card' }))
  expect(screen.getByText('INR')).toBeTruthy(); expect(document.documentElement.dataset.theme).toBe(appearance)
  expect(localStorage.length).toBe(0); expect(sessionStorage.length).toBe(0)
  const violations = (await axe.run(document.body, { rules: { 'color-contrast': { enabled: false } } })).violations
  expect(violations).toEqual([])
})

it.each(['\n', '\r', '\r\n', '\u2028', '\u2029'])('rejects terminal line separators in identity fields: %j', suffix => {
  expect(() => creditAccount({ ...active, id: active.id + suffix })).toThrow()
  expect(() => creditAccount({ ...active, label: active.label + suffix })).toThrow()
  expect(() => creditSource({ ...source, id: source.id + suffix })).toThrow()
})
it('defers its initial credit directory read while session validation is busy', async () => {
  render(<Workspace controller={auth} />); await screen.findByRole('heading', { name: 'A fresh start.' })
  let finish!: (value: Response) => void; const previous = fetchMock.getMockImplementation()!
  fetchMock.mockImplementation((path, options) => path === '/api/v1/auth/session' ? new Promise(resolve => { finish = resolve }) : previous(path, options))
  let checking!: Promise<void>; act(() => { checking = auth.check() })
  fireEvent.click(within(screen.getByRole('navigation', { name: 'Workspace navigation' })).getByRole('button', { name: 'Credit Cards' }))
  expect(creditCalls()).toHaveLength(0)
  await act(async () => { finish(response(session())); await checking })
  await screen.findByRole('heading', { name: 'Saved billing accounts' }); expect(creditCalls()).toHaveLength(1)
})
it.each(['lock', 'replacement session'])('drops late mapping replies after %s', async action => {
  await openSources(); let finish!: (value: Response) => void; const previous = fetchMock.getMockImplementation()!
  fetchMock.mockImplementation((path, options) => path === '/api/v1/finance/credit/sources/mappings/history' ? new Promise(resolve => { finish = resolve }) : previous(path, options))
  fireEvent.click(screen.getByRole('button', { name: `Link history for source ${source.id}` })); await screen.findByText('Checking saved credit identities…')
  if (action === 'lock') await act(async () => auth.lock())
  else { const pending = fetchMock.getMockImplementation()!; fetchMock.mockImplementation((path, options) => path === '/api/v1/auth/session' ? Promise.resolve(response({ ...session(), workspace_context: 'd'.repeat(64) })) : pending(path, options)); await act(async () => { auth.suspend(); await auth.bootstrap() }) }
  await act(async () => finish(response({ items: mappings(), next_before: null })))
  expect(document.querySelector('.wc-workspace')).toBeNull(); expect(document.body.innerHTML).not.toContain(source.id)
})
it('clears displayed source history when idle verification observes a replacement session', async () => {
  await openHistory(); const previous = fetchMock.getMockImplementation()!
  fetchMock.mockImplementation((path, options) => path === '/api/v1/auth/session' ? Promise.resolve(response({ ...session(), workspace_context: 'd'.repeat(64) })) : previous(path, options))
  await act(async () => auth.check())
  expect(auth.snapshot().screen).toMatchObject({ kind: 'blocked', reason: 'context' })
  expect(document.querySelector('.wc-workspace')).toBeNull(); expect(document.body.innerHTML).not.toContain(source.id)
})
it('rejects a source-link head regressing after a newer revision was observed', async () => {
  await openSources(); const newer = [mapping(4, { is_latest_revision: true }), ...mappings().map(item => ({ ...item, is_latest_revision: false }))]
  override('/api/v1/finance/credit/sources/mappings/history', () => ({ items: newer, next_before: null }))
  fireEvent.click(screen.getByRole('button', { name: `Link history for source ${source.id}` })); await screen.findByRole('heading', { name: 'Revision 4 · Link corrected' })
  override('/api/v1/finance/credit/sources/mappings/history', () => ({ items: mappings(), next_before: null }))
  fireEvent.click(screen.getByRole('button', { name: 'Refresh link history' })); await screen.findByRole('heading', { name: 'Unable to verify this response.' })
  expect(document.querySelector('.wc-workspace')).toBeNull()
})
it('rejects an empty link history after observing a first mapping for a formerly unlinked source', async () => {
  await openSources(); override('/api/v1/finance/credit/sources/mappings/history', () => ({ items: [mapping(1, { source_id: never.id, is_latest_revision: true })], next_before: null }))
  fireEvent.click(screen.getByRole('button', { name: `Link history for source ${never.id}` })); await screen.findByRole('heading', { name: 'Revision 1 · Initial link' })
  override('/api/v1/finance/credit/sources/mappings/history', () => ({ items: [], next_before: null }))
  fireEvent.click(screen.getByRole('button', { name: 'Refresh link history' })); await screen.findByRole('heading', { name: 'Unable to verify this response.' })
  expect(document.querySelector('.wc-workspace')).toBeNull()
})

it('keeps source history and visible action names accessible', async () => {
  await openHistory()
  expect(screen.getByRole('list', { name: 'Credit source link revisions' })).toBeTruthy()
  expect((await axe.run(document.body, { rules: { 'color-contrast': { enabled: false } } })).violations).toEqual([])
  for (const button of within(document.querySelector('.wc-workspace') as HTMLElement).getAllByRole('button')) {
    const label = button.getAttribute('aria-label')
    if (label) expect(label.toLowerCase()).toContain(button.textContent!.trim().toLowerCase())
  }
})
