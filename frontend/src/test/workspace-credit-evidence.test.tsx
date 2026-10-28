import { StrictMode } from 'react'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import axe from 'axe-core'
import Workspace from '../../workspace/src/Workspace'
import { AuthController } from '../../workspace/src/auth'
import { creditCashLabel, creditEvidence, creditEvidenceHistory, creditEvidenceInspection, creditEvidencePage, creditKindNames } from '../../workspace/src/credit-evidence'
import type { CreditKind } from '../../workspace/src/credit-evidence'
import type { CreditAccount } from '../../workspace/src/credit-identities'

const id = (value: number) => `7a000000-0000-4000-8000-${String(value).padStart(12, '0')}`
const account: CreditAccount = { id: id(1), issuer: 'hdfc', billing_currency: 'INR', label: 'Everyday card', revision: 1, state: 'active' }
const money = (source: string | null, currency = 'INR', missing_reason: string | null = source === null ? 'not_supplied' : null) => ({ source, currency, missing_reason })
function sample(kind: CreditKind, revision = 2, changes: Record<string, unknown> = {}) {
  const values = kind === 'statement' ? { period_start: '2026-09-01', period_end: '2026-09-30', statement_date: '2026-10-03', due_date: '2026-10-24', opening_liability: money('-0.00'), closing_liability: money('12345.60'), total_due: money(`${revision}.00`), minimum_due: money(null) } : kind === 'current' ? { as_of_date: '2026-10-24', as_of_instant: '2026-10-24T23:15:16.123456+05:30', outstanding: money('-123.40'), unbilled: money('0'), credit_limit: money('900000000000000001.20'), available_credit: money(null, 'INR', 'conflicting_evidence') } : { role: 'posted_debit', treatment: 'movement', transaction_date: '2026-09-21', posting_date: '2026-09-23', billing_amount: money('8999.90'), original_amount: money('100.00', 'USD') }
  return { id: id(kind === 'statement' ? 20 : kind === 'current' ? 21 : 22), kind, revision, previous_revision: revision === 1 ? null : revision - 1, source_id: id(10), mapping_revision: revision, account_id: account.id, account_state: 'active', is_latest_revision: revision === 2, values, ...changes }
}
const values = (kind: CreditKind, change: Record<string, unknown>) => sample(kind, 2, { values: { ...sample(kind).values, ...change } })
const known = (kind: CreditKind, revision = 2) => creditEvidence(sample(kind, revision), account, kind)
const historyRows = (kind: CreditKind, latest = 2) => Array.from({ length: latest }, (_, index) => sample(kind, latest - index, { is_latest_revision: index === 0 }))
const response = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store', Date: new Date().toUTCString() } })
const session = () => ({ status: 'authenticated', workspace_context: 'c'.repeat(64), expires_at: new Date(Date.now() + 28_800_000).toISOString(), idle_expires_at: new Date(Date.now() + 900_000).toISOString(), fresh_until: new Date(Date.now() + 300_000).toISOString(), factors: [id(99)], unverified_factors: [] })
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
    if (path === '/api/v1/finance/credit/accounts/query') return response({ items: [account], next_after: null })
    if (path === '/api/v1/finance/credit/accounts/inspect') return response(account)
    if (String(path).startsWith('/api/v1/finance/credit/evidence/')) {
      const body = JSON.parse(String(options?.body)), kind = body.kind as CreditKind
      if (String(path).endsWith('/query')) return response({ items: [sample(kind)], next_after: null })
      if (String(path).endsWith('/history')) return response({ items: historyRows(kind), next_before: null })
      return response(sample(kind, body.at_revision))
    }
    return response({}, 404)
  })
})
afterEach(() => { auth.lock(); vi.unstubAllGlobals(); document.cookie = 'trading_dev_csrf=; Max-Age=0; Path=/'; delete document.documentElement.dataset.theme })
function override(path: string, handler: (body: Record<string, unknown>) => unknown, status = 200) { const previous = fetchMock.getMockImplementation()!; fetchMock.mockImplementation((url, options) => url === path ? Promise.resolve(response(handler(JSON.parse(String(options?.body))), status)) : previous(url, options)) }
async function openAccount(strict = false) {
  const component = <Workspace controller={auth} />; render(strict ? <StrictMode>{component}</StrictMode> : component)
  await screen.findByRole('heading', { name: 'A fresh start.' })
  fireEvent.click(within(screen.getByRole('navigation', { name: 'Workspace navigation' })).getByRole('button', { name: 'Credit Cards' }))
  await screen.findByRole('heading', { name: 'Saved billing accounts' }); fireEvent.click(screen.getByRole('button', { name: `Inspect account ${account.label}` }))
  await screen.findByRole('heading', { name: 'Billing account identity' })
}
async function openEvidence(kind: CreditKind = 'statement', strict = false) { await openAccount(strict); fireEvent.click(screen.getByRole('button', { name: new RegExp(`^${creditKindNames[kind]}`) })); await screen.findByRole('heading', { name: 'Saved evidence on this page' }) }
async function openHistory(kind: CreditKind = 'statement') { await openEvidence(kind); fireEvent.click(screen.getByRole('button', { name: `Revision history for evidence ${sample(kind).id}` })); await screen.findByRole('heading', { name: 'Evidence revision history' }) }
const evidenceCalls = () => fetchMock.mock.calls.filter(([path]) => String(path).includes('/credit/evidence/'))

it.each(['statement', 'current', 'entry'] as const)('retains exact %s values and separates observed lifecycle from immutable evidence', kind => {
  expect(creditEvidence(sample(kind), account, kind)).toEqual(sample(kind))
  expect(creditEvidence(sample(kind, 2, { account_state: 'archived' }), account, kind).account_state).toBe('archived')
  expect(creditEvidenceInspection(sample(kind, 2, { account_state: 'archived', is_latest_revision: false }), account, known(kind)).is_latest_revision).toBe(false)
})
it('distinguishes original cash absence, missing, zero and negative-zero without number conversion', () => {
  for (const original of [null, money(null, 'USD'), money('0', 'USD'), money('-0.00', 'USD')]) {
    const item = creditEvidence(values('entry', { original_amount: original }), account, 'entry')
    expect(item.kind === 'entry' && item.values.original_amount).toEqual(original)
  }
  const current = known('current'); if (current.kind !== 'current') throw new Error('fixture')
  expect(creditCashLabel(current.values.credit_limit, false)).toBe('INR 900,000,000,000,000,001.20')
  expect(creditCashLabel(current.values.outstanding, false)).toBe('INR -123.40')
  expect(creditCashLabel(current.values.available_credit, false)).toBe('INR unavailable · conflicting evidence')
  for (const amount of [null, current.values.unbilled, current.values.available_credit]) expect(creditCashLabel(amount, true)).toBe('••••')
})
it.each([123.4, '', '+1', '01', '1e3', '1,000', 'NaN', 'Infinity', '1.001', '1000000000000000000', '1\n', '-1.00'])('rejects malformed or negative entry magnitudes %j', source => {
  expect(() => creditEvidence(values('entry', { billing_amount: money(source as string) }), account, 'entry')).toThrow()
})
it.each([{ source: null, currency: 'INR', missing_reason: null }, money('1', 'USD'), money('1', 'EUR'), money('1', 'INR', 'not_supplied'), money(null, 'INR', 'guessed'), { ...money('1'), normalized: '1.00' }])('rejects wrong billing identity or inconsistent missing fields %#', billing_amount => expect(() => creditEvidence(values('entry', { billing_amount }), account, 'entry')).toThrow())
it.each(['0000-01-01', '2026-02-29', '2026-13-01', '2026-01-00', '2026-01-01T00:00:00Z', '2026-1-01', '2026-01-01\n'])('rejects non-calendar date %j', transaction_date => expect(() => creditEvidence(values('entry', { transaction_date }), account, 'entry')).toThrow())
it.each(['2026-10-24T24:00:00Z', '2026-10-24T00:60:00Z', '2026-10-24T00:00:60Z', '2026-10-24T00:00:00', '2026-10-24T00:00:00-00:00', '2026-10-24T00:00:00+14:01', '2026-10-24T00:00:00+15:00', '2026-10-24T00:00:00+05:60', '2026-10-24T00:00:00.1234567Z', '2026-10-23T23:15:16+05:30', '2026-10-24T00:00:00Z\n'])('rejects ambiguous or unsupported source instant %j', as_of_instant => expect(() => creditEvidence(values('current', { as_of_instant }), account, 'current')).toThrow())
it('preserves microsecond source spelling and rejects UTC range overflow', () => {
  expect(known('current').values).toMatchObject({ as_of_instant: '2026-10-24T23:15:16.123456+05:30' })
  for (const [as_of_date, as_of_instant] of [['0001-01-01', '0001-01-01T00:00:00+14:00'], ['9999-12-31', '9999-12-31T23:59:59-14:00']]) expect(() => creditEvidence(values('current', { as_of_date, as_of_instant }), account, 'current')).toThrow()
})
it.each([{ role: 'pending_debit' }, { role: 'unresolved' }, { role: 'purchase' }, { treatment: 'paid' }, { billing_amount: money('-0.01') }, { original_amount: money('-1', 'USD') }, { raw_description: 'private' }])('rejects inconsistent entry semantics or extra source text %#', change => expect(() => creditEvidence(values('entry', change), account, 'entry')).toThrow())
it('preserves pending and unsupported interpretations without inventing movements', () => {
  expect(creditEvidence(values('entry', { role: 'pending_credit', posting_date: null }), account, 'entry').values).toMatchObject({ role: 'pending_credit', posting_date: null })
  expect(creditEvidence(values('entry', { role: 'unresolved', treatment: 'unsupported', billing_amount: money(null), original_amount: null }), account, 'entry').values).toMatchObject({ role: 'unresolved', treatment: 'unsupported' })
  expect(() => creditEvidence(values('statement', { period_start: '2026-10-01' }), account, 'statement')).toThrow()
  expect(() => creditEvidence(values('statement', { minimum_due: money('-1') }), account, 'statement')).toThrow()
  expect(() => creditEvidence(values('current', { credit_limit: money('-1') }), account, 'current')).toThrow()
})
it.each([{ id: id(0).replace('-8000-', '-') }, { id: '00000000-0000-0000-0000-000000000000' }, { account_id: id(2) }, { kind: 'current' }, { revision: 0 }, { revision: 9007199254740992 }, { previous_revision: null }, { mapping_revision: '2' }, { source_id: 'not-a-source' }, { account_state: 'deleted' }, { is_latest_revision: 'true' }, { raw: 'private' }])('rejects malformed scope or extra fields %#', change => expect(() => creditEvidence(sample('statement', 2, change), account, 'statement')).toThrow())
it('rejects missing fields and field-shaped arrays without exposing private response content', () => {
  const { values: _values, ...missing } = sample('statement')
  for (const raw of [missing, [], { ...sample('statement'), values: [] }, { ...sample('statement'), source_id: 'private-source-canary' }]) {
    expect(() => creditEvidence(raw, account, 'statement')).toThrow()
    try { creditEvidence(raw, account, 'statement') } catch (error) { expect(String(error)).not.toContain('private-source-canary') }
  }
})
it('checks every bounded query row and exact UUID continuations', () => {
  const items = Array.from({ length: 25 }, (_, index) => sample('statement', 2, { id: id(100 + index) }))
  expect(creditEvidencePage({ items, next_after: id(124) }, account, 'statement').items).toHaveLength(25)
  for (const page of [{ items: [items[1], items[0]], next_after: null }, { items: [items[0], items[0]], next_after: null }, { items, next_after: id(125) }, { items: [...items, sample('statement', 2, { id: id(125) })], next_after: null }, { items: [sample('statement', 1)], next_after: null }, { items: [items[0]], next_after: id(100) }, { items: [items[0], sample('statement', 2, { id: id(101), account_state: 'archived' })], next_after: null }, { items, next_after: null, count: 25 }]) expect(() => creditEvidencePage(page, account, 'statement')).toThrow()
  expect(() => creditEvidencePage({ items, next_after: null }, account, 'statement', id(100))).toThrow()
})
it('binds contiguous history and retains both the selected revision and a higher observed floor', () => {
  const root = known('statement'), items = historyRows('statement', 4)
  expect(creditEvidenceHistory({ items, next_before: null }, account, root).items).toHaveLength(4)
  expect(() => creditEvidenceHistory({ items: historyRows('statement', 3), next_before: null }, account, root, null, 4)).toThrow()
  const rewritten = items.map(row => row.revision === 2 ? { ...row, mapping_revision: 99 } : row)
  expect(() => creditEvidenceHistory({ items: rewritten, next_before: null }, account, root, null, 4)).toThrow()
  for (const rows of [[], items.slice(1), [items[0], items[2], items[3]], [items[0], items[1]], items.map(row => ({ ...row, source_id: id(11) })), items.map(row => ({ ...row, is_latest_revision: false }))]) expect(() => creditEvidenceHistory({ items: rows, next_before: null }, account, root, null, 4)).toThrow()
})
it('binds history page cursors, predecessor exhaustion and exact source/account revisions', () => {
  const root = known('statement', 30), items = Array.from({ length: 25 }, (_, index) => sample('statement', 30 - index, { is_latest_revision: index === 0 })), older = historyRows('statement', 5).map(row => ({ ...row, is_latest_revision: false }))
  expect(creditEvidenceHistory({ items, next_before: 6 }, account, root).next_before).toBe(6)
  expect(creditEvidenceHistory({ items: older, next_before: null }, account, root, 6).items).toHaveLength(5)
  for (const page of [{ items, next_before: 7 }, { items, next_before: null }]) expect(() => creditEvidenceHistory(page, account, root)).toThrow()
  for (const page of [{ items: older.slice(1), next_before: null }, { items: [], next_before: null }, { items: older, next_before: 1 }, { items: historyRows('statement', 5), next_before: null }]) expect(() => creditEvidenceHistory(page, account, root, 6)).toThrow()
  expect(creditEvidenceHistory({ items: [], next_before: null }, account, root, 1).items).toEqual([])
})
it.each([{ revision: 3, previous_revision: 2 }, { source_id: id(11) }, { mapping_revision: 3 }, { id: id(99) }, { values: { ...sample('statement').values, total_due: money('3.00') } }])('rejects substituted exact-revision inspection %#', change => expect(() => creditEvidenceInspection(sample('statement', 2, change), account, known('statement'))).toThrow())

it.each(['statement', 'current', 'entry'] as const)('rejects a known historical %s revision becoming newest during exact inspection', kind => {
  const selected = known(kind, 1)
  expect(() => creditEvidenceInspection(sample(kind, 1, { is_latest_revision: true }), account, selected)).toThrow()
})
it('blocks an exact inspection that reclassifies a known earlier revision as newest', async () => {
  await openHistory(); override('/api/v1/finance/credit/evidence/inspect', () => sample('statement', 1, { is_latest_revision: true }))
  fireEvent.click(screen.getByRole('button', { name: `Inspect revision 1 of evidence ${id(20)}` }))
  await screen.findByRole('heading', { name: 'Unable to verify this response.' }); expect(document.querySelector('.wce-workspace')).toBeNull()
})

it('requires explicit account and report-kind choices and reuses the protected request boundary', async () => {
  await openAccount(true); expect(evidenceCalls()).toHaveLength(0)
  fireEvent.click(screen.getByRole('button', { name: /^Statement evidence/ })); await screen.findByRole('heading', { name: 'Saved evidence on this page' })
  expect(evidenceCalls()).toHaveLength(1)
  expect(evidenceCalls()[0]?.[1]).toMatchObject({ method: 'POST', credentials: 'same-origin', mode: 'same-origin', cache: 'no-store', redirect: 'error', referrerPolicy: 'no-referrer', headers: expect.objectContaining({ 'X-Workspace-Context': 'c'.repeat(64), 'X-CSRFToken': 'synthetic-csrf-value-long-enough' }) })
  expect(JSON.parse(String(evidenceCalls()[0]?.[1]?.body))).toEqual({ account_id: account.id, kind: 'statement', limit: 25, after: null })
})
it.each(['statement', 'current', 'entry'] as const)('shows original %s values and exact retained provenance in a USD display', async kind => {
  currency = 'USD'; await openEvidence(kind)
  const item = sample(kind); fireEvent.click(screen.getByRole('button', { name: `Inspect revision 2 of evidence ${item.id}` }))
  await screen.findByRole('heading', { name: 'Retained revision 2' })
  expect(JSON.parse(String(evidenceCalls().at(-1)?.[1]?.body))).toEqual({ account_id: account.id, kind, id: item.id, at_revision: 2 })
  expect(screen.getByText(id(10))).toBeTruthy(); expect(screen.getByText('Frozen source-link revision')).toBeTruthy()
  if (kind === 'statement') { expect(screen.getByText('INR -0.00')).toBeTruthy(); expect(screen.getByText('INR 12,345.60')).toBeTruthy(); expect(screen.getByText('INR unavailable · not supplied')).toBeTruthy() }
  if (kind === 'current') { expect(screen.getByText('2026-10-24T23:15:16.123456+05:30')).toBeTruthy(); expect(screen.getByText('INR 900,000,000,000,000,001.20')).toBeTruthy() }
  if (kind === 'entry') { expect(screen.getByText('INR 8,999.90')).toBeTruthy(); expect(screen.getByText('USD 100.00')).toBeTruthy() }
  expect(document.body.textContent).not.toContain('Paid in full')
})
it.each(['statement', 'current', 'entry'] as const)('masks known, zero, missing and historical %s amounts in the entire rendered subtree', async kind => {
  masked = true; await openHistory(kind)
  const subtree = document.querySelector('.wce-workspace')!; expect(subtree.textContent).toContain('••••')
  for (const value of ['12345.60', '12,345.60', '-0.00', '8,999.90', '100.00', '900,000,000,000,000,001.20', 'INR unavailable', 'USD unavailable']) expect(subtree.outerHTML).not.toContain(value)
  fireEvent.click(screen.getByRole('button', { name: `Inspect revision 1 of evidence ${sample(kind).id}` })); await screen.findByRole('heading', { name: 'Retained revision 1' })
  expect(document.querySelector('.wce-workspace')!.textContent).toContain('••••'); expect(document.querySelector('.wce-workspace')!.outerHTML).not.toContain('1.00')
})
it('retains absent and present-missing original cash labels without fabricating a conversion', async () => {
  override('/api/v1/finance/credit/evidence/query', () => ({ items: [values('entry', { original_amount: null })], next_after: null })); await openEvidence('entry')
  expect(screen.getByText('Not supplied as a separate amount')).toBeTruthy()
  override('/api/v1/finance/credit/evidence/query', () => ({ items: [values('entry', { original_amount: money(null, 'USD') })], next_after: null })); fireEvent.click(screen.getByRole('button', { name: 'Refresh evidence' }))
  await screen.findByText('USD unavailable · not supplied'); expect(screen.queryByText('Not supplied as a separate amount')).toBeNull()
})
it('pages and refreshes query cursors without accumulating value pages', async () => {
  const items = Array.from({ length: 25 }, (_, index) => sample('statement', 2, { id: id(100 + index) }))
  override('/api/v1/finance/credit/evidence/query', body => body.after ? { items: [], next_after: null } : { items, next_after: id(124) })
  await openEvidence(); fireEvent.click(screen.getByRole('button', { name: 'Next evidence page' })); await screen.findByText('Evidence page 2 · 0 shown')
  expect(screen.queryByText('INR 12,345.60')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'Refresh evidence' })); await screen.findByText('Evidence page 2 · 0 shown')
  expect(JSON.parse(String(evidenceCalls().at(-1)?.[1]?.body)).after).toBe(id(124))
  fireEvent.click(screen.getByRole('button', { name: 'Previous evidence page' })); await screen.findByText('Evidence page 1 · 25 shown')
})
it('pages history, inspects the exact historical revision and retains current observed lifecycle independently', async () => {
  override('/api/v1/finance/credit/evidence/history', body => body.before === 6 ? { items: historyRows('statement', 5).map(row => ({ ...row, is_latest_revision: false })), next_before: null } : { items: Array.from({ length: 25 }, (_, index) => sample('statement', 30 - index, { is_latest_revision: index === 0 })), next_before: 6 })
  await openHistory(); fireEvent.click(screen.getByRole('button', { name: 'Earlier revisions' })); await screen.findByText('Revision 1 · Earlier retained')
  expect(screen.queryByText('Revision 30 · Newest retained')).toBeNull()
  override('/api/v1/finance/credit/evidence/inspect', body => sample('statement', Number(body.at_revision), { account_state: 'archived', is_latest_revision: false }))
  fireEvent.click(screen.getByRole('button', { name: `Inspect revision 1 of evidence ${id(20)}` })); await screen.findByRole('heading', { name: 'Retained revision 1' }); expect(screen.getByText('Archived')).toBeTruthy()
  expect(JSON.parse(String(evidenceCalls().at(-1)?.[1]?.body)).at_revision).toBe(1)
})
it.each(['refresh', 'inspect return'] as const)('rejects a newer observed history head regressing through %s', async route => {
  override('/api/v1/finance/credit/evidence/history', () => ({ items: historyRows('statement', 4), next_before: null }))
  await openHistory(); await screen.findByText('Revision 4 · Newest retained')
  if (route === 'inspect return') { fireEvent.click(screen.getByRole('button', { name: `Inspect revision 1 of evidence ${id(20)}` })); await screen.findByRole('heading', { name: 'Retained revision 1' }) }
  override('/api/v1/finance/credit/evidence/history', () => ({ items: historyRows('statement', 3), next_before: null }))
  fireEvent.click(screen.getByRole('button', { name: route === 'refresh' ? 'Refresh revisions' : `Revision history for evidence ${id(20)}` }))
  await screen.findByRole('heading', { name: 'Unable to verify this response.' }); expect(document.querySelector('.wce-workspace')).toBeNull()
})
it.each([404, 409, 429, 503])('clears exact evidence/account context and reloads the directory after status %i', async status => {
  await openEvidence(); override('/api/v1/finance/credit/evidence/inspect', () => ({}), status)
  fireEvent.click(screen.getByRole('button', { name: `Inspect revision 2 of evidence ${id(20)}` })); await screen.findByText('Credit evidence could not be verified.')
  expect(screen.queryByText(account.label)).toBeNull(); expect(document.body.innerHTML).not.toContain('12,345.60'); expect(auth.snapshot().screen.kind).toBe('workspace')
  fireEvent.click(screen.getByRole('button', { name: 'Reload credit accounts' })); await screen.findByRole('heading', { name: 'Saved billing accounts' })
  expect(fetchMock.mock.calls.at(-1)?.[0]).toBe('/api/v1/finance/credit/accounts/query')
})
it('blocks a malformed later row before showing any financial value', async () => {
  override('/api/v1/finance/credit/evidence/query', () => ({ items: [sample('statement'), sample('statement', 2, { id: id(21), account_id: id(2), raw: 'private-canary' })], next_after: null }))
  await openAccount(); fireEvent.click(screen.getByRole('button', { name: /^Statement evidence/ })); await screen.findByRole('heading', { name: 'Unable to verify this response.' })
  expect(document.body.innerHTML).not.toContain('12,345.60'); expect(document.body.innerHTML).not.toContain('private-canary')
})
it.each([401, 403, 412])('removes private evidence on protected boundary status %i', async status => {
  await openEvidence(); override('/api/v1/finance/credit/evidence/query', () => ({}), status); fireEvent.click(screen.getByRole('button', { name: 'Refresh evidence' }))
  await vi.waitFor(() => expect(auth.snapshot().screen.kind).not.toBe('workspace')); expect(document.querySelector('.wce-workspace')).toBeNull()
})
it.each(['navigate', 'logout', 'lock', 'replacement session'] as const)('discards late financial responses after %s', async action => {
  await openEvidence(); let finish!: (value: Response) => void; const previous = fetchMock.getMockImplementation()!
  fetchMock.mockImplementation((path, options) => path === '/api/v1/finance/credit/evidence/history' ? new Promise(resolve => { finish = resolve }) : previous(path, options))
  fireEvent.click(screen.getByRole('button', { name: `Revision history for evidence ${id(20)}` })); await screen.findByText('Checking saved credit evidence…')
  expect(document.body.innerHTML).not.toContain('12,345.60')
  if (action === 'navigate') fireEvent.click(within(screen.getByRole('navigation', { name: 'Workspace navigation' })).getByRole('button', { name: 'Overview' }))
  else if (action === 'logout') fireEvent.click(screen.getByRole('button', { name: 'Sign out here' }))
  else if (action === 'lock') await act(async () => auth.lock())
  else { const pending = fetchMock.getMockImplementation()!; fetchMock.mockImplementation((path, options) => path === '/api/v1/auth/session' ? Promise.resolve(response({ ...session(), workspace_context: 'd'.repeat(64) })) : pending(path, options)); await act(async () => { auth.suspend(); await auth.bootstrap() }) }
  await act(async () => finish(response({ items: historyRows('statement'), next_before: null })))
  expect(document.querySelector('.wce-workspace')).toBeNull(); expect(document.body.innerHTML).not.toContain('12,345.60')
})
it.each(['light', 'dark'])('supports keyboard focus, masking and accessible semantics in %s without persistence', async appearance => {
  theme = appearance; await openAccount(); const user = userEvent.setup(); const choice = screen.getByRole('button', { name: /^Statement evidence/ }); await waitFor(() => expect((choice as HTMLButtonElement).disabled).toBe(false)); choice.focus(); await user.keyboard('{Enter}')
  await screen.findByRole('heading', { name: 'Saved evidence on this page' }); expect(document.activeElement).toBe(screen.getByRole('heading', { name: 'Statement evidence' }))
  const button = screen.getByRole('button', { name: `Inspect revision 2 of evidence ${id(20)}` }); await waitFor(() => expect((button as HTMLButtonElement).disabled).toBe(false)); button.focus(); await user.keyboard('{Enter}')
  await screen.findByRole('heading', { name: 'Retained revision 2' }); expect(document.activeElement).toBe(screen.getByRole('heading', { name: 'Retained revision 2' }))
  expect((await axe.run(document.body, { rules: { 'color-contrast': { enabled: false } } })).violations).toEqual([])
  expect(localStorage.length).toBe(0); expect(sessionStorage.length).toBe(0); expect(document.documentElement.dataset.theme).toBe(appearance)
  for (const action of within(document.querySelector('.wce-workspace') as HTMLElement).getAllByRole('button')) { const label = action.getAttribute('aria-label'); if (label) expect(label.toLowerCase()).toContain(action.textContent!.trim().toLowerCase()) }
})
