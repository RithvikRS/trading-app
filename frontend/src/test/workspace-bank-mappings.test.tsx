import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import axe from 'axe-core'
import Workspace from '../../workspace/src/Workspace'
import { AuthController } from '../../workspace/src/auth'
import { MAX_BANK_MAPPING_REVISION, bankMappingAnchor, bankMappingChange, bankMappingHistory, bankMappingResult, bankMappingTransition, bankSourceAnchor, bankSourceState, eligibleBankTarget, mappingAccounts, mappingSources } from '../../workspace/src/bank-mappings'
import type { BankMappingCommand, BankMappingTransition, MappingSource } from '../../workspace/src/bank-mappings'
import type { Account } from '../../workspace/src/accounts'

const id = (n: number) => `bc000000-0000-4000-8000-${String(n).padStart(12, '0')}`
const scope = { source_id: id(100), namespace: 'hdfc_statement' as const }
const account = (n = 1, changes: Partial<Account> = {}): Account => ({ id: id(n), kind: 'bank', institution: 'hdfc', market: 'IN', label: n === 1 ? 'Primary savings' : 'Other savings', currencies: ['INR'], revision: 1, state: 'active', ...changes })
const source = (changes: Partial<MappingSource> = {}): MappingSource => ({ id: scope.source_id, namespace: scope.namespace, mapping_revision: null, account_id: null, state: 'unmapped', ...changes })
const transition = (revision = 1, account_id: string | null = id(1), selected = scope): BankMappingTransition => ({ ...selected, revision, previous_revision: revision === 1 ? null : revision - 1, account_id, reason: account_id === null ? 'unlinked' : revision === 1 ? 'initial' : 'correction' })
const anchor = (head: BankMappingTransition | null = null) => bankMappingAnchor({ ...scope, head_revision: head?.revision ?? 0, head })
const history = (items: BankMappingTransition[] = [], before: number | null = null) => {
  const head = items.at(-1) ?? null, selected = head ?? scope
  const page = [...items].reverse().filter(item => before === null || item.revision < before).slice(0, 25), last = page.at(-1)
  return { source_id: selected.source_id, namespace: selected.namespace, head_revision: head?.revision ?? 0, head, items: page, next_before: last && last.revision > 1 ? last.revision : null }
}
const target = (n = 1) => eligibleBankTarget(account(n), scope)!
const session = (context = 'c'.repeat(64)) => ({ status: 'authenticated', workspace_context: context, expires_at: new Date(Date.now() + 28_800_000).toISOString(), idle_expires_at: new Date(Date.now() + 900_000).toISOString(), fresh_until: new Date(Date.now() + 300_000).toISOString(), factors: [id(999)], unverified_factors: [] })
const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store', Date: new Date().toUTCString() } })
const fetchMock = vi.fn<typeof fetch>()
let auth: AuthController, accounts: Account[], sources: MappingSource[], chain: BankMappingTransition[], theme: string
const calls = () => fetchMock.mock.calls.filter(([path]) => String(path).startsWith('/api/v1/finance/'))
const changes = () => calls().filter(([path]) => String(path).endsWith('/bank-source-mappings/change'))
const histories = () => calls().filter(([path]) => String(path).endsWith('/bank-source-mappings/history'))
function sourceProjection(): MappingSource[] {
  return sources.map(item => {
    if (item.id !== scope.source_id) return item
    const head = chain.at(-1)
    return { ...item, mapping_revision: head?.revision ?? null, account_id: head?.account_id ?? null, state: !head?.account_id ? 'unmapped' : accounts.find(account => account.id === head.account_id)?.state === 'archived' ? 'archived' : 'mapped' }
  })
}
function append(account_id: string | null) { const item = transition((chain.at(-1)?.revision ?? 0) + 1, account_id); chain.push(item); return item }
function change(body: BankMappingCommand): Response {
  const prior = chain.find(item => item.revision === body.expected_revision), replay = chain.find(item => item.revision === body.expected_revision + 1)
  if (replay && replay.account_id === body.account_id && (prior?.account_id ?? null) !== body.account_id) return response(replay)
  const head = chain.at(-1)
  if (body.source_id !== scope.source_id || body.expected_revision !== (head?.revision ?? 0) || body.account_id === (head?.account_id ?? null)) return response({ private: 'conflict detail' }, 409)
  if (body.account_id !== null && !accounts.some(item => item.id === body.account_id && eligibleBankTarget(item, scope))) return response({}, 409)
  return response(append(body.account_id))
}
function override(path: string, handler: (body: Record<string, unknown>) => Response | Promise<Response>) {
  const prior = fetchMock.getMockImplementation()!
  fetchMock.mockImplementation((url, options) => url === '/api/v1/finance' + path ? Promise.resolve(handler(JSON.parse(String(options?.body ?? '{}')))) : prior(url, options))
}
beforeEach(() => {
  accounts = [account(), account(2), account(3, { institution: 'sbi', label: 'SBI account' }), account(4, { label: 'Archived account', state: 'archived' }), account(5, { kind: 'brokerage', institution: 'indmoney', label: 'Brokerage account' })]
  sources = [source(), source({ id: id(101), namespace: 'indmoney_us' })]; chain = []; theme = 'light'
  document.cookie = 'trading_dev_csrf=synthetic-csrf-value-long-enough; Path=/'
  vi.stubGlobal('fetch', fetchMock); fetchMock.mockReset(); auth = new AuthController()
  fetchMock.mockImplementation(async (url, options) => {
    if (url === '/api/v1/auth/bootstrap') return response({ status: 'ready', recovery_email_enabled: false })
    if (url === '/api/v1/auth/session') return response(session())
    if (url === '/api/v1/auth/logout') return response({ status: 'signed_out', provider_cleanup: 'complete' })
    if (url === '/api/v1/preferences') return response({ theme, display_currency: 'USD', amount_masked: true, revision: 1 })
    const body = JSON.parse(String(options?.body ?? '{}'))
    if (url === '/api/v1/finance/accounts/query') return response({ items: accounts, next_after: null })
    if (url === '/api/v1/finance/sources/query') return response({ items: sourceProjection(), next_after: null })
    if (url === '/api/v1/finance/bank-source-mappings/history') return response(history(chain, body.before))
    if (url === '/api/v1/finance/bank-source-mappings/change') return change(body)
    return response({}, 404)
  })
})
afterEach(() => { auth.lock(); vi.useRealTimers(); vi.unstubAllGlobals(); document.cookie = 'trading_dev_csrf=; Max-Age=0; Path=/'; delete document.documentElement.dataset.theme })
async function directory() {
  const user = userEvent.setup(), result = render(<Workspace controller={auth} />)
  await screen.findByRole('heading', { name: 'A fresh start.' })
  await user.click(within(screen.getByRole('navigation', { name: 'Workspace navigation' })).getByRole('button', { name: 'Accounts' }))
  await waitFor(() => expect((screen.getByRole('button', { name: 'Review bank source assignments' }) as HTMLButtonElement).disabled).toBe(false))
  return { user, ...result }
}
async function openSources() { const result = await directory(); await result.user.click(screen.getByRole('button', { name: 'Review bank source assignments' })); await screen.findByRole('heading', { name: 'Choose a saved bank source.' }); return result }
async function reviewSource() { const result = await openSources(); await result.user.click(screen.getByRole('button', { name: `Review assignment for source ${scope.source_id}` })); await screen.findByRole('heading', { name: 'Review this source assignment.' }); return result }
function choose(name = 'Primary savings') { fireEvent.click(screen.getByRole('radio', { name: new RegExp(name) })); fireEvent.click(screen.getByRole('checkbox', { name: 'I reviewed the source, latest history and account directory and intend this change.' })) }
function submit() { fireEvent.submit(screen.getByRole('checkbox', { name: 'I reviewed the source, latest history and account directory and intend this change.' }).closest('form')!) }
async function saved() { await screen.findByRole('complementary', { name: 'Historical saved transition' }); await waitFor(() => expect(auth.snapshot().busy).toBe(false)) }

it('validates the entire mixed source page before narrowing bank namespaces', () => {
  const mixed = { items: [source(), source({ id: id(101), namespace: 'indmoney_us' })], next_after: null }
  expect(mappingSources(mixed).items).toHaveLength(2)
  expect(() => mappingSources({ ...mixed, items: [source(), { ...mixed.items[1], reference: 'private source detail' }] })).toThrow()
  expect(() => mappingSources({ ...mixed, owner_id: id(999) })).toThrow()
})
it.each([
  { id: id(100).toUpperCase() }, { id: id(100) + '\n' }, { id: '00000000-0000-0000-0000-000000000000' },
  { namespace: 'hdfc_credit_statement' }, { mapping_revision: 0 }, { mapping_revision: true }, { mapping_revision: 1.5 },
  { mapping_revision: MAX_BANK_MAPPING_REVISION + 1 }, { account_id: id(1), mapping_revision: null, state: 'mapped' },
  { state: 'mapped' }, { account_id: id(1), mapping_revision: 1, state: 'unmapped' }, { mapping_revision: 1, account_id: null },
])('rejects inconsistent source projection %#', patch => expect(() => mappingSources({ items: [{ ...source(), ...patch }], next_after: null })).toThrow())
it('keeps source pagination honest on empty filtered pages and rejects duplicate/reversed/cursor-before rows', () => {
  const page = Array.from({ length: 25 }, (_, index) => source({ id: id(100 + index), namespace: 'indmoney_us' }))
  expect(mappingSources({ items: page, next_after: id(124) }).next_after).toBe(id(124))
  for (const items of [[source(), source()], [...page].reverse(), [...page, source({ id: id(125) })]]) expect(() => mappingSources({ items, next_after: null })).toThrow()
  expect(() => mappingSources({ items: [source()], next_after: source().id })).toThrow()
  expect(() => mappingSources({ items: [source()], next_after: null }, id(100))).toThrow()
})
it('distinguishes never linked, explicitly unlinked and an archived target', () => {
  expect(bankSourceState(source())).toBe('Never linked')
  expect(bankSourceState(source({ mapping_revision: 2 }))).toBe('Explicitly unlinked')
  expect(bankSourceState(source({ mapping_revision: 1, account_id: id(1), state: 'archived' }))).toBe('Linked to archived account')
})
it('validates all account fields before offering compatible active safe bank targets', () => {
  expect(mappingAccounts({ items: accounts, next_after: null }).items).toHaveLength(5)
  expect(accounts.map(item => eligibleBankTarget(item, scope)).filter(Boolean)).toHaveLength(2)
  expect(eligibleBankTarget(account(1, { label: 'Account 1234' }), scope)).toBeNull()
  expect(eligibleBankTarget(account(1, { currencies: ['USD', 'INR'] }), scope)).toBeNull()
  expect(() => mappingAccounts({ items: [...accounts.slice(0, 4), { ...accounts[4], private_ref: 'never render' }], next_after: null })).toThrow()
})
it.each([{ kind: 'brokerage' }, { institution: 'sbi' }, { market: 'US' }] as const)('rejects a present current target outside the selected source family: %j', patch => {
  expect(() => mappingAccounts({ items: [account(1, patch)], next_after: null }, null, anchor(transition()))).toThrow()
})
it('allows archived current targets, off-page targets and unrelated mixed rows without applying new-target admission', () => {
  const archived = account(1, { state: 'archived', label: 'Legacy account 1234', currencies: ['USD', 'INR'] })
  const unrelated = account(2, { kind: 'brokerage', institution: 'indmoney', market: 'US' })
  expect(mappingAccounts({ items: [archived, unrelated], next_after: null }, null, anchor(transition())).items).toEqual([archived, unrelated])
  expect(mappingAccounts({ items: [unrelated], next_after: null }, null, anchor(transition())).items).toEqual([unrelated])
  expect(mappingAccounts({ items: [account(1, { institution: 'sbi' })], next_after: null }, null, anchor()).items).toHaveLength(1)
})
it.each([{ kind: 'brokerage' }, { institution: 'sbi' }, { market: 'US' }] as const)('clears the protected view before displaying incompatible current-target status: %j', async patch => {
  chain = [transition()]; accounts[0] = account(1, patch)
  const { user } = await openSources()
  await user.click(screen.getByRole('button', { name: `Review assignment for source ${scope.source_id}` }))
  await screen.findByRole('heading', { name: 'Unable to verify this response.' })
  expect(document.querySelector('.bm-assignments')).toBeNull(); expect(document.body.textContent).not.toContain('Primary savings'); expect(changes()).toHaveLength(0)
})
it('revalidates a present current target inside the protected pre-submit account projection', async () => {
  chain = [transition()]; await reviewSource(); choose('Unlink this source')
  accounts[0] = account(1, { market: 'US', revision: 2 }); submit()
  await screen.findByRole('heading', { name: 'Unable to verify this response.' })
  expect(document.querySelector('.bm-assignments')).toBeNull(); expect(changes()).toHaveLength(0)
})
it('holds immutable source scope and equal-revision source/head tuples across repeat observations', () => {
  const observed = bankSourceAnchor(source({ mapping_revision: 1, account_id: id(1), state: 'mapped' }))
  expect(() => bankSourceAnchor(source(), observed)).toThrow()
  expect(() => bankSourceAnchor(source({ namespace: 'sbi_statement', mapping_revision: 1, account_id: id(1), state: 'mapped' }), observed)).toThrow()
  expect(() => bankSourceAnchor(source({ mapping_revision: 1, account_id: id(2), state: 'mapped' }), observed)).toThrow()
  expect(() => mappingSources({ items: [source({ mapping_revision: 1, account_id: id(2), state: 'mapped' })], next_after: null }, null, new Map([[scope.source_id, observed]]))).toThrow()
})
it.each([
  { source_id: id(101) }, { namespace: 'sbi_statement' }, { revision: 0 }, { revision: true }, { revision: 1.1 }, { revision: '1' },
  { revision: MAX_BANK_MAPPING_REVISION + 1 }, { previous_revision: 1 }, { account_id: null }, { reason: 'correction' }, { is_current: true },
])('rejects malformed or scope-substituted change result %#', patch => expect(() => bankMappingResult({ ...transition(), ...patch }, bankMappingChange(anchor(), target()))).toThrow())
it('enforces exact history windows, contiguous predecessors, full head consistency and no adjacent noops', () => {
  const chain = [transition(), transition(2, null), transition(3, id(2))]
  const page = history(chain)
  expect(bankMappingHistory(page, anchor()).items).toHaveLength(3)
  expect(bankMappingHistory(history(chain, 2), anchor(chain[2]), 2).items).toHaveLength(1)
  const invalid = [
    { ...page, source_id: id(101) }, { ...page, namespace: 'sbi_statement', head: { ...page.head, namespace: 'sbi_statement' }, items: page.items.map(item => ({ ...item, namespace: 'sbi_statement' })) },
    { ...page, head_revision: 2 }, { ...page, head: null }, { ...page, head: { ...page.head, account_id: id(1) } },
    { ...page, items: page.items.slice(0, 2) }, { ...page, items: [page.items[0], page.items[0], page.items[2]] }, { ...page, next_before: 1 },
    history([transition(), transition(2, id(1))]), { ...page, private_ref: 'hidden' },
  ]
  for (const value of invalid) expect(() => bankMappingHistory(value, anchor())).toThrow()
  expect(() => bankMappingHistory(page, anchor(), 3)).toThrow()
})
it('pins an earlier observed head tuple when a newer head and an older page arrive', () => {
  const original = transition(2, id(2)), observed = anchor(original)
  expect(() => bankMappingHistory(history([transition(), original, transition(3, null)]), anchor(transition(3, id(1))))).toThrow()
  expect(() => bankMappingHistory(history([transition(), transition(2, null), transition(3, id(1))]), observed)).toThrow()
  expect(() => bankMappingHistory(history([transition()]), observed)).toThrow()
  expect(bankMappingHistory(history([transition(), original, transition(3, null)]), observed).head_revision).toBe(3)
})
it('keeps a numeric existence floor and historical result separate from an observed head', () => {
  const initial = anchor(), savedResult = transition()
  expect(() => bankMappingHistory(history(), initial, null, 1, savedResult)).toThrow()
  expect(() => bankMappingHistory(history([transition(1, id(2))]), initial, null, 1, savedResult)).toThrow()
  const latest = bankMappingHistory(history([savedResult, transition(2, null), transition(3, id(2))]), initial, null, 1, savedResult)
  expect(latest.head_revision).toBe(3); expect(initial.head_revision).toBe(0); expect(savedResult.revision).toBe(1)
  expect(() => mappingSources({ items: [source()], next_after: null }, null, new Map([[scope.source_id, initial]]), new Map([[scope.source_id, savedResult]]))).toThrow()
})
it('accepts inclusive MAX head/history cursors but refuses an append from MAX', () => {
  const maximum = MAX_BANK_MAPPING_REVISION
  const items = Array.from({ length: 26 }, (_, index) => transition(maximum - 25 + index, id(index % 2 ? 1 : 2)))
  const selected = anchor(items.at(-1)!)
  expect(bankMappingHistory(history(items, maximum), selected, maximum).items[0]!.revision).toBe(maximum - 1)
  expect(() => bankMappingChange(selected, target(2))).toThrow()
  expect(() => bankMappingHistory(history(items), selected, maximum + 1)).toThrow()
  const previous = anchor(transition(maximum - 1, id(1))), pending = bankMappingChange(previous, target(2))
  expect(bankMappingResult(transition(maximum, id(2)), pending).revision).toBe(maximum)
})
it('freezes exact predecessor and target, refuses initial unlink and noops, and accepts old equivalent transition evidence', () => {
  expect(() => bankMappingChange(anchor(), null)).toThrow()
  expect(() => bankMappingChange(anchor(transition()), target())).toThrow()
  const pending = bankMappingChange(anchor(transition()), target(2))
  expect(Object.isFrozen(bankMappingTransition(transition()))).toBe(true)
  expect(Object.isFrozen(pending)).toBe(true); expect(Object.isFrozen(pending.command)).toBe(true); expect(Object.isFrozen(pending.target?.currencies)).toBe(true)
  expect(bankMappingResult(transition(2, id(2)), pending).revision).toBe(2)
  expect(() => bankMappingResult(transition(3, id(2)), pending)).toThrow()
  expect(() => bankMappingResult(transition(2, id(1)), pending)).toThrow()
})
it('requires explicit source entry and keeps all identity reads/writes behind finance POST protection', async () => {
  await auth.finance('/sources/query', { limit: 25, after: null }, mappingSources); expect(fetchMock).not.toHaveBeenCalled()
  await directory(); expect(calls().map(([path]) => path)).toEqual(['/api/v1/finance/accounts/query'])
  fireEvent.click(screen.getByRole('button', { name: 'Review bank source assignments' })); await screen.findByRole('heading', { name: 'Choose a saved bank source.' })
  expect(changes()).toHaveLength(0); expect(histories()).toHaveLength(0)
  expect(calls().at(-1)).toEqual(['/api/v1/finance/sources/query', expect.objectContaining({ method: 'POST', body: JSON.stringify({ limit: 25, after: null }), credentials: 'same-origin', mode: 'same-origin', redirect: 'error', cache: 'no-store', referrerPolicy: 'no-referrer', headers: expect.objectContaining({ 'X-CSRFToken': 'synthetic-csrf-value-long-enough', 'X-Workspace-Context': 'c'.repeat(64) }) })])
})
it('distinguishes duplicate account names and currencies by full internal ID through selection and retry', async () => {
  accounts[1] = account(2, { label: 'Primary savings' })
  let firstAttempt = true
  override('/bank-source-mappings/change', body => { if (firstAttempt) { firstAttempt = false; return response({}, 503) }; return change(body as BankMappingCommand) })
  await reviewSource()
  expect(screen.getByRole('radio', { name: new RegExp(`Primary savings.*Account ID ${id(1)}`) })).toBeTruthy()
  fireEvent.click(screen.getByRole('radio', { name: new RegExp(`Primary savings.*Account ID ${id(2)}`) }))
  fireEvent.click(screen.getByRole('checkbox', { name: /I reviewed the source/ })); submit()
  await screen.findByRole('heading', { name: 'The change is not confirmed.' })
  expect(within(document.querySelector('.bm-pending') as HTMLElement).getByText(`Account ID ${id(2)}`)).toBeTruthy()
  expect(JSON.parse(String(changes()[0]![1]!.body))).toEqual({ source_id: scope.source_id, expected_revision: 0, account_id: id(2) })
  fireEvent.click(screen.getByRole('button', { name: 'Retry the same change' })); await saved()
  expect(changes()[1]![1]!.body).toBe(changes()[0]![1]!.body); expect(chain.at(-1)?.account_id).toBe(id(2))
})
it('links, corrects and unlinks through explicit reviewed changes while retaining immutable history', async () => {
  await reviewSource(); expect(screen.queryByRole('radio', { name: /Unlink this source/ })).toBeNull()
  expect(screen.queryByRole('radio', { name: /SBI account|Archived account|Brokerage account/ })).toBeNull()
  choose(); submit(); await saved(); expect(chain).toEqual([transition()])
  expect(screen.queryByRole('radio', { name: /Primary savings/ })).toBeNull()
  expect(within(screen.getByRole('complementary', { name: 'Historical saved transition' })).getByText(/does not prove which request created it/)).toBeTruthy()
  choose('Other savings'); submit(); await saved(); expect(chain.at(-1)).toEqual(transition(2, id(2)))
  choose('Unlink this source'); submit(); await saved(); expect(chain.at(-1)).toEqual(transition(3, null))
  expect(screen.getByText('Explicitly unlinked · Head revision 3')).toBeTruthy(); expect(changes()).toHaveLength(3)
  expect(JSON.parse(String(changes()[0]![1]!.body))).toEqual({ source_id: scope.source_id, expected_revision: 0, account_id: id(1) })
})
it('uses a mixed-page cursor even when no bank sources appear, and never seeds an empty directory', async () => {
  const mixed = Array.from({ length: 25 }, (_, index) => source({ id: id(10 + index), namespace: 'indmoney_us' }))
  override('/sources/query', body => body.after === null ? response({ items: mixed, next_after: id(34) }) : response({ items: [source()], next_after: null }))
  await openSources(); expect(screen.getByText(/No HDFC or SBI sources on this page/)).toBeTruthy(); expect(screen.queryByRole('button', { name: `Review assignment for source ${scope.source_id}` })).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'Next source page' })); await screen.findByRole('button', { name: `Review assignment for source ${scope.source_id}` })
  expect(calls().at(-1)?.[1]?.body).toBe(JSON.stringify({ limit: 25, after: id(34) })); expect(changes()).toHaveLength(0)
})
it('opens an archived target as history and offers unlink or a different active account', async () => {
  chain = [transition(1, id(4))]; await reviewSource()
  expect(screen.getByText('Linked to archived account · Head revision 1')).toBeTruthy()
  expect(screen.getByRole('radio', { name: /Unlink this source/ })).toBeTruthy(); expect(screen.queryByRole('radio', { name: /Archived account/ })).toBeNull()
  choose('Unlink this source'); submit(); await saved(); expect(chain.at(-1)?.account_id).toBeNull()
})
it('retries the exact predecessor and target after a lost response, later correction and target archive', async () => {
  let lost = true
  override('/bank-source-mappings/change', body => { const result = change(body as BankMappingCommand); if (lost) { lost = false; return response({}, 503) } return result })
  await reviewSource(); choose(); submit(); await screen.findByRole('heading', { name: 'The change is not confirmed.' }); expect(chain).toHaveLength(1)
  append(id(2)); accounts[0] = account(1, { state: 'archived', revision: 2 })
  const before = histories().length
  fireEvent.click(screen.getByRole('button', { name: 'Retry the same change' })); await saved()
  expect(changes()).toHaveLength(2); expect(changes()[1]![1]!.body).toBe(changes()[0]![1]!.body); expect(chain).toHaveLength(2)
  expect(histories()).toHaveLength(before + 1); expect(screen.getByText('Linked · Head revision 2')).toBeTruthy()
  expect(within(screen.getByRole('complementary', { name: 'Historical saved transition' })).getByText('Initial link · Revision 1')).toBeTruthy()
})
it('does not silently adopt a changed head before a new change and requires review again', async () => {
  await reviewSource(); choose(); append(id(2)); submit(); await screen.findByRole('heading', { name: 'Review this source assignment.' })
  expect(changes()).toHaveLength(0); expect(screen.getByText('Linked · Head revision 1')).toBeTruthy()
  expect((screen.getByRole('checkbox', { name: /I reviewed the source/ }) as HTMLInputElement).checked).toBe(false)
  choose('Primary savings'); submit(); await saved(); expect(JSON.parse(String(changes()[0]![1]!.body)).expected_revision).toBe(1)
})
it('rechecks the selected account page and refuses an archived target before posting', async () => {
  await reviewSource(); choose(); accounts[0] = account(1, { state: 'archived', revision: 2 }); submit()
  await screen.findByText('The account directory changed. Review it and choose again.')
  expect(changes()).toHaveLength(0); expect(screen.queryByRole('radio', { name: /Primary savings/ })).toBeNull()
})
it('clears conflicting context and requires source directory and history review before another command', async () => {
  override('/bank-source-mappings/change', () => response({ private: 'never render' }, 409))
  await reviewSource(); choose(); submit(); await screen.findByText('The assignment needs a fresh review.')
  expect(screen.queryByRole('button', { name: 'Retry the same change' })).toBeNull(); expect(within(document.querySelector('.bm-panel') as HTMLElement).queryByText('Primary savings')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'Review saved sources' })); await screen.findByRole('heading', { name: 'Choose a saved bank source.' })
  expect(changes()).toHaveLength(1); expect(screen.queryByRole('checkbox', { name: /I reviewed the source/ })).toBeNull()
})
it.each([429, 503])('retains only an explicit exact retry after unavailable change HTTP%s', async status => {
  override('/bank-source-mappings/change', () => response({ private: 'never render' }, status))
  await reviewSource(); choose(); submit(); await screen.findByRole('heading', { name: 'The change is not confirmed.' })
  expect(changes()).toHaveLength(1); expect(screen.queryByRole('radio', { name: /Primary savings/ })).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'Retry the same change' })); await screen.findByRole('heading', { name: 'The change is not confirmed.' })
  expect(changes()[1]![1]!.body).toBe(changes()[0]![1]!.body); expect(document.body.textContent).not.toContain('never render')
})
it('guards synchronous double-submit and freezes the target before a delayed fresh-history check', async () => {
  await reviewSource(); choose(); let finish!: (response: Response) => void
  override('/bank-source-mappings/history', () => new Promise(resolve => { finish = resolve }))
  const form = screen.getByRole('checkbox', { name: /I reviewed the source/ }).closest('form')!
  act(() => { fireEvent.submit(form); fireEvent.submit(form) }); expect(changes()).toHaveLength(0)
  override('/bank-source-mappings/history', () => response(history(chain)))
  await act(async () => finish(response(history())))
  await saved(); expect(changes()).toHaveLength(1); expect(JSON.parse(String(changes()[0]![1]!.body)).account_id).toBe(id(1))
})
it.each([401, 403, 412, 'malformed'] as const)('clears all private mapping state through the global change boundary on%s', async failure => {
  override('/bank-source-mappings/change', () => failure === 'malformed' ? response({ ...transition(), private_ref: 'never render' }) : response({ private: 'never render' }, failure))
  await reviewSource(); choose(); submit(); await waitFor(() => expect(auth.snapshot().screen.kind).not.toBe('workspace'))
  expect(document.querySelector('.bm-assignments')).toBeNull(); expect(document.body.textContent).not.toMatch(/Primary savings|never render|bc000000/)
})
it('rejects an invalid non-bank source before filtering or rendering the page', async () => {
  override('/sources/query', () => response({ items: [source(), { ...source({ id: id(101), namespace: 'advisor' }), external_reference: 'never render' }], next_after: null }))
  await directory(); fireEvent.click(screen.getByRole('button', { name: 'Review bank source assignments' })); await screen.findByRole('heading', { name: 'Unable to verify this response.' })
  expect(document.body.textContent).not.toContain('never render'); expect(changes()).toHaveLength(0)
})
it.each(['namespace', 'same-revision tuple', 'regression'])('globally rejects a repeated selected-history%s substitution', async failure => {
  chain = [transition()]; await reviewSource()
  override('/bank-source-mappings/history', () => {
    if (failure === 'regression') return response(history())
    if (failure === 'same-revision tuple') return response(history([transition(1, id(2))]))
    return response({ ...history(chain), namespace: 'sbi_statement', head: { ...transition(), namespace: 'sbi_statement' }, items: [{ ...transition(), namespace: 'sbi_statement' }] })
  })
  fireEvent.click(screen.getByRole('button', { name: 'Refresh current assignment' })); await screen.findByRole('heading', { name: 'Unable to verify this response.' })
  expect(document.querySelector('.bm-assignments')).toBeNull()
})
it('keeps historical completion separate when current source refresh is unavailable', async () => {
  await reviewSource(); override('/sources/query', () => response({}, 503)); choose(); submit()
  await screen.findByRole('heading', { name: 'Saved transition found.' }); expect(screen.getByRole('complementary', { name: 'Historical saved transition' })).toBeTruthy()
  expect(screen.queryByText('Latest observed assignment')).toBeNull(); expect(screen.queryByRole('button', { name: 'Retry the same change' })).toBeNull(); expect(changes()).toHaveLength(1)
})
it.each(['navigate', 'lock', 'session'] as const)('discards late change results after%s without replaying or promoting them to a head', async action => {
  let finish!: (response: Response) => void, pending!: BankMappingCommand
  override('/bank-source-mappings/change', body => { pending = body as BankMappingCommand; return new Promise(resolve => { finish = resolve }) })
  await reviewSource(); choose(); submit(); await screen.findByText('Saving the assignment change…')
  if (action === 'navigate') fireEvent.click(within(screen.getByRole('navigation', { name: 'Workspace navigation' })).getByRole('button', { name: 'Overview' }))
  else if (action === 'lock') await act(async () => auth.lock())
  else await act(async () => { auth.suspend(); await auth.bootstrap() })
  await act(async () => finish(change(pending)))
  expect(document.querySelector('.bm-panel')).toBeNull(); expect(changes()).toHaveLength(1)
  if (action !== 'lock') {
    fireEvent.click(within(screen.getByRole('navigation', { name: 'Workspace navigation' })).getByRole('button', { name: 'Accounts' }))
    await waitFor(() => expect((screen.getByRole('button', { name: 'Review bank source assignments' }) as HTMLButtonElement).disabled).toBe(false))
    fireEvent.click(screen.getByRole('button', { name: 'Review bank source assignments' })); await screen.findByRole('heading', { name: 'Choose a saved bank source.' })
    expect(screen.queryByRole('button', { name: 'Retry the same change' })).toBeNull(); expect(screen.queryByRole('radio')).toBeNull(); expect(changes()).toHaveLength(1)
  }
})
it('never posts after leaving during the pre-submit history read', async () => {
  await reviewSource(); choose(); let finish!: (response: Response) => void
  override('/bank-source-mappings/history', () => new Promise(resolve => { finish = resolve })); submit(); await screen.findByText('Checking the assignment before changing it…')
  fireEvent.click(within(screen.getByRole('navigation', { name: 'Workspace navigation' })).getByRole('button', { name: 'Overview' }))
  await act(async () => finish(response(history())))
  expect(changes()).toHaveLength(0); expect(document.querySelector('.bm-panel')).toBeNull()
})
it('clears uncertain context on offline and does not restore it after page re-entry', async () => {
  override('/bank-source-mappings/change', () => response({}, 503)); await reviewSource(); choose(); submit(); await screen.findByRole('heading', { name: 'The change is not confirmed.' })
  fireEvent(window, new Event('offline')); expect(document.querySelector('.bm-panel')).toBeNull(); expect(document.body.textContent).not.toContain(scope.source_id)
  await act(async () => auth.bootstrap()); expect(changes()).toHaveLength(1); expect(document.querySelector('.bm-panel')).toBeNull()
})
it('locks a retained mapping view when an idle session check detects owner replacement', async () => {
  await reviewSource(); const previous = fetchMock.getMockImplementation()!
  fetchMock.mockImplementation((path, options) => path === '/api/v1/auth/session' ? Promise.resolve(response(session('d'.repeat(64)))) : previous(path, options))
  await act(async () => auth.check()); expect(auth.snapshot().screen).toMatchObject({ kind: 'blocked', reason: 'context' }); expect(document.querySelector('.bm-panel')).toBeNull()
})
it.each(['light', 'dark'])('supports keyboard/accessibility and no browser storage or generated request IDs in%s mode', async appearance => {
  theme = appearance; const store = vi.spyOn(Storage.prototype, 'setItem'), read = vi.spyOn(Storage.prototype, 'getItem'), uuid = vi.spyOn(crypto, 'randomUUID')
  const { user, container } = await directory()
  screen.getByRole('button', { name: 'Review bank source assignments' }).focus(); await user.keyboard('{Enter}'); await screen.findByRole('heading', { name: 'Choose a saved bank source.' })
  expect(document.activeElement).toBe(screen.getByRole('heading', { name: 'Choose a saved bank source.' }))
  screen.getByRole('button', { name: `Review assignment for source ${scope.source_id}` }).focus(); await user.keyboard('{Enter}'); await screen.findByRole('heading', { name: 'Review this source assignment.' })
  screen.getByRole('radio', { name: /Primary savings/ }).focus(); await user.keyboard(' '); screen.getByRole('checkbox', { name: /I reviewed the source/ }).focus(); await user.keyboard(' ')
  expect((await axe.run(container, { rules: { 'color-contrast': { enabled: false } } })).violations).toEqual([])
  screen.getByRole('button', { name: 'Link source to account' }).focus(); await user.keyboard('{Enter}'); await saved()
  expect((await axe.run(container, { rules: { 'color-contrast': { enabled: false } } })).violations).toEqual([])
  expect(store).not.toHaveBeenCalled(); expect(read).not.toHaveBeenCalled(); expect(uuid).not.toHaveBeenCalled()
})

it('keeps current head evidence while paginating older transitions and requires latest review for a change', async () => {
  chain = Array.from({ length: 30 }, (_, index) => transition(index + 1, id(index % 2 ? 2 : 1)))
  await reviewSource(); expect(within(screen.getByRole('list', { name: 'Assignment transitions' })).getAllByRole('listitem')).toHaveLength(25)
  append(id(1)); fireEvent.click(screen.getByRole('button', { name: 'Earlier assignment history' })); await screen.findByText('Linked · Head revision 31')
  expect(JSON.parse(String(histories().at(-1)![1]!.body)).before).toBe(6)
  expect(within(screen.getByRole('list', { name: 'Assignment transitions' })).getAllByRole('listitem')).toHaveLength(5)
  expect(screen.queryByRole('checkbox', { name: /I reviewed the source/ })).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'Latest assignment history' })); await screen.findByRole('checkbox', { name: /I reviewed the source/ })
  expect(screen.getByText('Linked · Head revision 31')).toBeTruthy(); expect(changes()).toHaveLength(0)
})
it('selects a compatible account beyond an entirely ineligible first mixed page without claiming its later absence', async () => {
  const mixed = Array.from({ length: 25 }, (_, index) => account(index + 1, { institution: 'sbi', label: 'Other institution account' }))
  const later = account(26, { label: 'Target on later page' })
  accounts = [later]
  override('/accounts/query', body => body.after === null ? response({ items: mixed, next_after: id(25) }) : response({ items: [later], next_after: null }))
  await reviewSource(); expect(screen.getByText(/No different eligible bank account on this page/)).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: 'Next account page' })); await screen.findByRole('radio', { name: /Target on later page/ })
  choose('Target on later page'); submit(); await saved()
  expect(JSON.parse(String(changes()[0]![1]!.body)).account_id).toBe(later.id)
  expect(screen.getByText('The target account is not on this directory page. Its current status is not shown here.')).toBeTruthy()
  expect(within(screen.getByRole('complementary', { name: 'Historical saved transition' })).getByText(later.id)).toBeTruthy()
})
it('keeps terminal revision history readable while refusing further append actions', async () => {
  chain = Array.from({ length: 26 }, (_, index) => transition(MAX_BANK_MAPPING_REVISION - 25 + index, id(index % 2 ? 1 : 2)))
  await reviewSource(); expect(screen.getByText(/reached the supported revision limit/)).toBeTruthy()
  expect(screen.queryByRole('checkbox', { name: /I reviewed the source/ })).toBeNull()
  expect((screen.getByRole('button', { name: 'Earlier assignment history' }) as HTMLButtonElement).disabled).toBe(false); expect(changes()).toHaveLength(0)
})
it('treats an unknown selected source as unavailable rather than an empty history', async () => {
  override('/bank-source-mappings/history', () => response({ private: 'unknown owner source' }, 409))
  await openSources(); fireEvent.click(screen.getByRole('button', { name: `Review assignment for source ${scope.source_id}` })); await screen.findByText('Saved assignments could not be checked.')
  expect(screen.queryByText(/No transitions in this history window/)).toBeNull(); expect(document.body.textContent).not.toContain('unknown owner source'); expect(changes()).toHaveLength(0)
})
it('does not accept current projections below the existence floor proven by a saved transition', async () => {
  await reviewSource()
  override('/sources/query', () => response({ items: [source()], next_after: null }))
  choose(); submit(); await screen.findByRole('heading', { name: 'Unable to verify this response.' })
  expect(chain).toHaveLength(1); expect(document.querySelector('.bm-panel')).toBeNull(); expect(changes()).toHaveLength(1)
})
it('keeps HDFC and SBI target compatibility independent of native and display currency', () => {
  const sbi = { source_id: id(200), namespace: 'sbi_statement' as const }
  expect(eligibleBankTarget(account(1, { currencies: ['USD'] }), scope)?.currencies).toEqual(['USD'])
  expect(eligibleBankTarget(account(1), sbi)).toBeNull()
  expect(eligibleBankTarget(account(3, { institution: 'sbi', currencies: ['INR', 'USD'] }), sbi)?.id).toBe(id(3))
})
