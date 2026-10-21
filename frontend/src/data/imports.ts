import { bankNames, getBankTransactions } from './banking'
import type { BankId, BankTransaction } from './banking'
import { money } from './money'
import type { Currency, Money } from './money'

export const importIds = ['i01', 'i02', 'i03', 'i04', 'i05', 'i06', 'i07'] as const
export type ImportId = typeof importIds[number]
export const isImportId = (value: string): value is ImportId => importIds.some(id => id === value)
export const dispositions = { new: 'New candidate', present: 'Already present', duplicate: 'Duplicate within batch', overlap: 'Possible overlap', conflict: 'Conflict', invalid: 'Invalid / unsupported' } as const
export type Disposition = keyof typeof dispositions
export const isDisposition = (value: string): value is Disposition => Object.hasOwn(dispositions, value)
export interface OriginalRow {
  provider: string; account: string; owner: string; transactionId: string; kind: string
  bookingDate: string; valueDate: string; dateFormat: string; direction: string; amount: string; currency: string; status: string
  description: string; reference: string; narration: string
}
export interface IncomingRow { id: string; original: OriginalRow }
export interface ImportBatch {
  id: ImportId; name: string; subtitle: string; account: BankId; owner: string; provider: string; currency: Currency
  source: string; revision: string; fingerprint: string; from: string; to: string; activityAsOf: string; balanceAsOf: string
  complete: boolean; coverageNote: string; opening: Money | null; closing: Money | null
  baseline: { id: string; description: string; receivedFingerprints: string[]; rows: IncomingRow[] }
  rows: IncomingRow[]
  distinctPairs?: { incomingId: string; baselineId: string; reason: string }[]
}
export interface NormalizedRow {
  account: BankId | null; owner: string | null; provider: string | null; transactionId: string | null
  date: string | null; valueDate: string | null; valueDateSupplied: boolean; amount: Money | null; direction: 'debit' | 'credit' | null; status: 'posted' | 'pending' | null
  issues: string[]
}
export interface PreviewRow { row: IncomingRow; normalized: NormalizedRow; disposition: Disposition; reasons: string[]; matches: IncomingRow[]; canonicalId: string | null }
export interface NativeGroup { currency: Currency; status: 'posted' | 'pending'; count: number; credits: Money; debits: Money; net: Money }
const sampleOwner = 'sample-owner'
const provider = (account: BankId) => `${account}-statement-example`
function decimal(value: Money) { return `${value.minor / 100n}.${(value.minor % 100n).toString().padStart(2, '0')}` }
function fromRecord(record: BankTransaction): IncomingRow {
  return { id: `row-${record.id}`, original: { provider: provider(record.accountId), account: record.accountId, owner: record.ownerId, transactionId: `source-${record.id}`, kind: 'bank-activity', bookingDate: record.date, valueDate: record.valueDate ?? '', dateFormat: 'YYYY-MM-DD', direction: record.direction, amount: decimal(record.amount), currency: record.amount.currency, status: record.status, description: record.description, reference: record.reference, narration: record.narration } }
}
function copyRow(row: IncomingRow, id = row.id, overrides: Partial<OriginalRow> = {}): IncomingRow { return { id, original: { ...row.original, ...overrides } } }
function fixtureBatch(id: ImportId, name: string, subtitle: string, account: BankId, rows: IncomingRow[], baselineRows: IncomingRow[], options: Partial<ImportBatch> = {}): ImportBatch {
  return { id, name, subtitle, account, owner: sampleOwner, provider: provider(account), currency: 'INR', source: `Fictional ${bankNames[account]} October statement`, revision: 'r1', fingerprint: `example-${id}-r1`, from: '2026-10-01', to: '2026-10-20', activityAsOf: '20 Oct 2026, 10:00 IST', balanceAsOf: '20 Oct 2026, 10:00 IST', complete: true, coverageNote: 'Month to date through 20 October, 10:00 IST. Later activity is not supplied.', opening: money(account === 'hdfc' ? '177285.90' : '38199'), closing: money(account === 'hdfc' ? '186420' : '74850'), baseline: { id: `comparison-${id}-r1`, description: baselineRows.length ? 'Selected bundled source records · Fixed comparison copy' : 'Empty example store · No comparison records', receivedFingerprints: [], rows: baselineRows.map(row => copyRow(row)) }, rows: rows.map(row => copyRow(row)), ...options }
}

// These are normalized fictional examples, not supported provider file formats.
// Baselines intentionally differ by scenario and never represent the live Banking store.
export function getImportBatches(): ImportBatch[] {
  const records = getBankTransactions(false), hdfc = records.filter(row => row.accountId === 'hdfc').map(fromRecord), sbi = records.filter(row => row.accountId === 'sbi').map(fromRecord)
  const replay = fixtureBatch('i02', 'An exact replay', 'An already-received statement and its existing rows.', 'hdfc', hdfc, hdfc)
  replay.baseline.receivedFingerprints = [replay.fingerprint]
  const repeated = hdfc.filter(row => ['source-t05', 'source-t06'].includes(row.original.transactionId))
  return [
    fixtureBatch('i01', 'A first statement', 'A reconciling HDFC sample with posted and pending activity.', 'hdfc', hdfc, []),
    replay,
    fixtureBatch('i03', 'An overlapping statement', 'Some rows already exist; one similar payment needs interpretation.', 'hdfc', hdfc, hdfc.slice(0, 5), { distinctPairs: [{ incomingId: 'row-t06', baselineId: 'row-t05', reason: 'The sample source identifies two separate café payments with different transaction identities and references.' }] }),
    fixtureBatch('i04', 'Similar payments, separate identities', 'Two café payments and one exact repeated row.', 'hdfc', [...repeated, copyRow(repeated[0]!, 'row-t05-copy')], [], { complete: false, opening: null, closing: null, balanceAsOf: 'Not supplied', from: '2026-10-05', to: '2026-10-05', coverageNote: 'Selected payment excerpt. Opening/closing balances and complete period coverage were never supplied.' }),
    fixtureBatch('i05', 'A conflicting source record', 'SBI reports a changed amount under an existing source identity.', 'sbi', sbi.map(row => row.original.transactionId === 'source-t26' ? copyRow(row, row.id, { amount: '2300.00', narration: 'FICTIONAL RECORD / Water and maintenance bill / INR 2300.00 / DEBIT' }) : row), sbi),
    fixtureBatch('i06', 'Fields that need attention', 'Ambiguous dates, malformed money, missing identity, and incompatible records.', 'hdfc', [
      copyRow(hdfc[0]!, 'issue-date', { bookingDate: '10/11/2026', dateFormat: 'Unspecified' }),
      copyRow(hdfc[1]!, 'issue-amount', { amount: '22,000' }),
      copyRow(hdfc[2]!, 'issue-value-date', { valueDate: '2026-02-30' }),
      copyRow(hdfc[3]!, 'issue-identity', { transactionId: '' }),
      copyRow(hdfc[4]!, 'issue-owner', { owner: 'sample-other-owner', account: 'sbi' }),
      copyRow(hdfc[5]!, 'issue-currency', { currency: 'USD' }),
      copyRow(hdfc[6]!, 'issue-kind', { kind: 'security-event', description: '<img src=x onerror=alert(1)>', narration: 'FICTIONAL RAW TEXT / <script>alert(1)</script> / INR 3200.00' }),
    ], [], { complete: false, coverageNote: 'A validation excerpt, not a complete statement. Some readable amounts have other invalid fields.' }),
    fixtureBatch('i07', 'An incomplete statement', 'SBI activity is missing a bill while its balance remains separately supplied.', 'sbi', sbi.filter(row => row.original.transactionId !== 'source-t26'), [], { complete: false, activityAsOf: '19 Oct 2026, 10:00 IST', coverageNote: 'Missing bill on 19 October; activity is stale through 20 October. The supplied closing balance has a separate date.' }),
  ]
}

function parsedDate(value: string, format: string): string | null {
  const iso = format === 'YYYY-MM-DD' && /^\d{4}-\d{2}-\d{2}$/.test(value) ? value : format === 'DD/MM/YYYY' && /^\d{2}\/\d{2}\/\d{4}$/.test(value) ? `${value.slice(6)}-${value.slice(3, 5)}-${value.slice(0, 2)}` : null
  if (!iso || iso < '1900-01-01' || iso > '2100-12-31') return null
  const time = Date.parse(`${iso}T00:00:00Z`)
  return Number.isFinite(time) && new Date(time).toISOString().slice(0, 10) === iso ? iso : null
}
function parsedAmount(value: string, currency: string): Money | null {
  if ((currency !== 'INR' && currency !== 'USD') || !/^\d{1,9}(\.\d{1,2})?$/.test(value)) return null
  const result = money(value, currency)
  return result.minor > 0n ? result : null
}
export function normalizeImportRow(row: IncomingRow, batch?: ImportBatch): NormalizedRow {
  const raw = row.original, issues: string[] = []
  const account = raw.account === 'hdfc' || raw.account === 'sbi' ? raw.account : null
  const owner = raw.owner === sampleOwner ? raw.owner : null
  const source = account && raw.provider === provider(account) ? raw.provider : null
  const transactionId = /^[a-zA-Z0-9-]{1,64}$/.test(raw.transactionId) ? raw.transactionId : null
  const date = parsedDate(raw.bookingDate, raw.dateFormat), valueDate = raw.valueDate ? parsedDate(raw.valueDate, raw.dateFormat) : null
  const amount = parsedAmount(raw.amount, raw.currency)
  const direction = raw.direction === 'debit' || raw.direction === 'credit' ? raw.direction : null
  const status = raw.status === 'posted' || raw.status === 'pending' ? raw.status : null
  if (!account || !source || !owner || (batch && (account !== batch.account || raw.provider !== batch.provider || raw.owner !== batch.owner))) issues.push('Source account, owner, or institution does not match the known sample scope.')
  if (!transactionId) issues.push('A valid scoped source transaction identity is required.')
  if (!date) issues.push(raw.dateFormat === 'Unspecified' ? 'Booking date is ambiguous without an explicit source format.' : 'Booking date does not match a supported explicit format or calendar date.')
  else if (batch && (date < batch.from || date > batch.to)) issues.push('Booking date lies outside the supplied statement period.')
  if (raw.valueDate && !valueDate) issues.push('Value date is not a valid calendar date in the declared format.')
  if (!amount) issues.push('Amount or currency is unsupported. Use a positive bounded decimal with at most two places; unavailable is not zero.')
  if (amount && batch && amount.currency !== batch.currency) issues.push('Original currency does not match the statement currency. No FX is used to repair it.')
  if (!direction || !status || raw.kind !== 'bank-activity') issues.push('Direction, posting status, or record kind is unsupported.')
  if (!raw.description.trim() || !raw.reference.trim() || raw.description.length > 200 || raw.reference.length > 160 || raw.narration.length > 500) issues.push('Source description, reference, or narration is missing or exceeds the supported sample bounds.')
  return { account, owner, provider: source, transactionId, date, valueDate, valueDateSupplied: Boolean(raw.valueDate), amount, direction, status, issues }
}
function scopeKey(row: IncomingRow) { const raw = row.original; return JSON.stringify([raw.provider, raw.owner, raw.account, raw.transactionId]) }
function evidenceKey(row: IncomingRow, normalized: NormalizedRow) {
  const raw = row.original
  return JSON.stringify([normalized.date, normalized.valueDate, normalized.direction, normalized.amount?.minor.toString(), raw.currency, normalized.status, raw.kind, raw.description, raw.reference, raw.narration])
}
function samePayment(left: PreviewRow, right: IncomingRow, normalized: NormalizedRow) {
  const a = left.normalized, b = normalized
  return a.provider === b.provider && a.owner === b.owner && a.account === b.account && a.date === b.date && a.direction === b.direction && a.status === b.status && a.amount?.currency === b.amount?.currency && a.amount?.minor === b.amount?.minor && left.row.original.description === right.original.description
}
export function previewImport(batch: ImportBatch) {
  const baseline = batch.baseline.rows.map(row => ({ row, normalized: normalizeImportRow(row) }))
  const prepared: PreviewRow[] = batch.rows.map(row => {
    const normalized = normalizeImportRow(row, batch)
    if (!/^[a-z0-9-]{1,64}$/.test(row.id) || batch.rows.filter(other => other.id === row.id).length !== 1) normalized.issues.push('Incoming row identity is invalid or repeated; each source occurrence needs a distinct stable row ID.')
    return { row, normalized, disposition: 'new', reasons: [], matches: [], canonicalId: null }
  })
  const rows: PreviewRow[] = prepared.map(item => {
    if (item.normalized.issues.length) return { ...item, disposition: 'invalid', reasons: item.normalized.issues }
    const identity = scopeKey(item.row), evidence = evidenceKey(item.row, item.normalized)
    const siblings = prepared.filter(other => scopeKey(other.row) === identity)
    const existing = baseline.filter(other => scopeKey(other.row) === identity)
    if (siblings.some(other => other.normalized.issues.length || evidenceKey(other.row, other.normalized) !== evidence) || existing.length > 1 || existing.some(other => other.normalized.issues.length || evidenceKey(other.row, other.normalized) !== evidence)) {
      return { ...item, disposition: 'conflict', reasons: ['The same scoped source identity has different immutable fields or ambiguous baseline evidence. No version is overwritten.'], matches: [...existing.map(other => other.row), ...siblings.filter(other => other.row.id !== item.row.id).map(other => other.row)] }
    }
    const canonical = siblings.map(other => other.row.id).sort()[0]!
    if (canonical !== item.row.id) return { ...item, disposition: 'duplicate', canonicalId: canonical, reasons: ['Identical scoped identity and immutable fields repeat within this batch. Inspect the canonical row; count its candidate effect at most once.'] }
    if (existing.length === 1) return { ...item, disposition: 'present', matches: [existing[0]!.row], reasons: ['Scoped identity and immutable source fields match the comparison baseline. Proposed treatment: skip; this row adds no new candidate movement.'] }
    const similar = baseline.filter(other => !other.normalized.issues.length && samePayment(item, other.row, other.normalized))
    if (similar.length) return { ...item, disposition: 'overlap', matches: similar.map(other => other.row), reasons: ['Date, description, direction, and amount resemble baseline evidence under a different identity. Similarity does not prove a duplicate; interpretation remains unresolved.'] }
    return { ...item, reasons: ['Known sample scope and required fields are valid; no matching identity or similar baseline record was found. This is a candidate only.'] }
  })
  const counts = Object.fromEntries(Object.keys(dispositions).map(key => [key, rows.filter(row => row.disposition === key).length])) as Record<Disposition, number>
  const source = nativeGroups(rows), candidates = nativeGroups(rows.filter(row => row.disposition === 'new'))
  const amountComplete = source.unreadable === 0 && source.groups.every(group => group.currency === batch.currency)
  const native = source.groups.find(group => group.currency === batch.currency && group.status === 'posted')
  const movement = amountComplete ? native?.net ?? money('0', batch.currency) : null
  const computed = movement && batch.opening ? { currency: batch.currency, minor: batch.opening.minor + movement.minor } : null
  const difference = computed && batch.closing ? { currency: batch.currency, minor: batch.closing.minor - computed.minor } : null
  return { rows, counts, source, candidates, replay: batch.baseline.receivedFingerprints.includes(batch.fingerprint), reconciliation: { movement, computed, difference, status: difference === null ? 'unavailable' as const : difference.minor === 0n ? 'matches' as const : 'difference' as const } }
}
export function nativeGroups(rows: readonly PreviewRow[]) {
  const groups: NativeGroup[] = []; let unreadable = 0
  for (const { normalized: row } of rows) {
    if (!row.amount || !row.direction || !row.status) { unreadable++; continue }
    let group = groups.find(value => value.currency === row.amount!.currency && value.status === row.status)
    if (!group) { group = { currency: row.amount.currency, status: row.status, count: 0, credits: money('0', row.amount.currency), debits: money('0', row.amount.currency), net: money('0', row.amount.currency) }; groups.push(group) }
    group.count++
    if (row.direction === 'credit') group.credits = { ...group.credits, minor: group.credits.minor + row.amount.minor }
    else group.debits = { ...group.debits, minor: group.debits.minor + row.amount.minor }
    group.net = { ...group.net, minor: group.credits.minor - group.debits.minor }
  }
  return { groups: groups.sort((a, b) => a.currency.localeCompare(b.currency) || b.status.localeCompare(a.status)), unreadable }
}
export interface ImportFilters { query: string; disposition: Disposition | 'all'; account: BankId | 'all' }
export interface ImportControls { query: string; account: BankId | 'all'; batches: Partial<Record<ImportId, { filters: ImportFilters; selected: string | null }>> }
export const initialImportFilters: ImportFilters = { query: '', disposition: 'all', account: 'all' }
export function createImportControls(): ImportControls { return { query: '', account: 'all', batches: {} } }
export function clearImportSearch(state: ImportControls): ImportControls { return { ...state, query: '', batches: Object.fromEntries(Object.entries(state.batches).map(([id, value]) => [id, value ? { ...value, filters: { ...value.filters, query: '' } } : value])) } }
export function clearImportSelection(state: ImportControls): ImportControls { return { ...state, batches: Object.fromEntries(Object.entries(state.batches).map(([id, value]) => [id, value ? { ...value, selected: null } : value])) } }
export function selectImportRows(rows: readonly PreviewRow[], filters: ImportFilters) {
  const query = filters.query.slice(0, 80).trim().toLocaleLowerCase('en-US')
  return rows.filter(item => (filters.disposition === 'all' || filters.disposition === item.disposition) && (filters.account === 'all' || filters.account === item.row.original.account) && (!query || `${item.row.original.description} ${item.row.original.reference}`.toLocaleLowerCase('en-US').includes(query)))
}
