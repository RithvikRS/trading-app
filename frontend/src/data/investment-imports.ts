import { getHoldings, QUOTE_SCALE, UNIT_SCALE, valueHolding } from './holdings'
import type { Holding } from './holdings'
import { getEmployeeLots, getHoldingActivity } from './holdingRecords'
import { parseFixed } from './money'
import type { Currency, Money } from './money'
import type { Disposition } from './imports'

export const investmentImportIds = ['i08', 'i09', 'i10', 'i11', 'i12', 'i13', 'i14'] as const
export type InvestmentImportId = typeof investmentImportIds[number]
export const isInvestmentImportId = (id: string): id is InvestmentImportId => investmentImportIds.some(value => value === id)
export const investmentSources = { 'ind-in': 'INDmoney India', 'ind-us': 'INDmoney US', advisor: 'Advisor funds', ubs: 'UBS employee shares' } as const
export type InvestmentAccount = keyof typeof investmentSources
export const isInvestmentAccount = (value: string): value is InvestmentAccount => Object.hasOwn(investmentSources, value)
export const recordKinds = { position: 'Holdings snapshot', activity: 'Activity record', cash: 'Cash record', lot: 'Lot record' } as const
export type InvestmentKind = keyof typeof recordKinds
export interface InvestmentRaw {
  source: string; recordId: string; kind: string; event: string; owner: string; account: string; instrument: string; scheme: string
  plan: string; option: string; form: string; folio: string; snapshotAt: string; date: string; currency: string
  units: string; quote: string; quoteAt: string; purchasePrice: string; amount: string; fee: string; withholding: string; net: string; basis: string
  description: string; narration: string
}
export interface InvestmentRow { id: string; original: InvestmentRaw }
export interface PositionCheckpoint { holdingId: string; snapshotAt: string; units: string; opening: string | null }
export interface CashCheckpoint { account: InvestmentAccount; currency: Currency; snapshotAt: string; closing: string; opening: string | null }
export interface InvestmentBatch {
  id: InvestmentImportId; name: string; subtitle: string; account: InvestmentAccount; mode: 'snapshot' | 'activity' | 'lots'
  revision: string; fingerprint: string; from: string; to: string; scope: string; coverage: string; complete: boolean
  accounts: InvestmentAccount[]; positions: PositionCheckpoint[]; cash: CashCheckpoint[]; rows: InvestmentRow[]
  baseline: { id: string; rows: InvestmentRow[] }
}
export interface NormalizedInvestment {
  kind: InvestmentKind | null; holding: Holding | null; currency: Currency | null; units: bigint | null; quote: bigint | null; purchasePrice: bigint | null
  value: Money | null; amount: Money | null; fee: Money | null; withholding: Money | null; net: Money | null; basis: Money | null
  issues: string[]; warnings: string[]
}
export interface InvestmentPreviewRow { row: InvestmentRow; normalized: NormalizedInvestment; disposition: Disposition; reasons: string[]; matches: InvestmentRow[]; canonicalId: string | null }
export const investmentEvidence = (value: unknown) => JSON.stringify(value, (_key, field: unknown) => typeof field === 'bigint' ? field.toString() : field)
const decimal = (value: bigint, scale: number) => `${value / 10n ** BigInt(scale)}.${(value % 10n ** BigInt(scale)).toString().padStart(scale, '0')}`
const sourceFor = (account: string) => account === 'ubs' ? 'ubs-example' : account === 'advisor' ? 'advisor-example' : 'indmoney-example'
const family = (holding: Holding) => holding.instrument.type === 'fund' ? holding.instrument.id.replace(/-(direct|regular)$/, '') : ''
const blank: InvestmentRaw = { source: '', recordId: '', kind: '', event: '', owner: 'sample-owner', account: '', instrument: '', scheme: '', plan: '', option: '', form: '', folio: '', snapshotAt: '', date: '', currency: '', units: '', quote: '', quoteAt: '', purchasePrice: '', amount: '', fee: '', withholding: '', net: '', basis: '', description: '', narration: '' }
function holdingRow(holding: Holding): InvestmentRow {
  return { id: `position-${holding.id}`, original: { ...blank, source: sourceFor(holding.accountId), recordId: `position-${holding.id}`, kind: 'position', account: holding.accountId, instrument: holding.instrument.id, scheme: family(holding), plan: holding.instrument.plan ?? '', option: holding.instrument.option ?? '', form: holding.instrument.type === 'fund' ? 'SOA' : 'demat', folio: holding.folio ?? '', snapshotAt: holding.holdingsDate, currency: holding.instrument.currency, units: decimal(holding.units, UNIT_SCALE), quote: holding.quote ? decimal(holding.quote.amount, QUOTE_SCALE) : '', quoteAt: holding.quote?.date ?? '', description: holding.instrument.name, narration: 'Fictional selected position; transaction and tax history are not implied.' } }
}
const copy = (row: InvestmentRow, id = row.id, fields: Partial<InvestmentRaw> = {}): InvestmentRow => ({ id, original: { ...row.original, ...fields } })
function cashRow(account: InvestmentAccount, amount: string, date: string): InvestmentRow {
  return { id: `cash-${account}`, original: { ...blank, source: sourceFor(account), recordId: `cash-${account}`, kind: 'cash', event: 'balance', account, snapshotAt: date, currency: account === 'ind-in' || account === 'advisor' ? 'INR' : 'USD', amount, description: 'Broker cash snapshot', narration: 'Fictional cash balance, not a cash movement or investment value.' } }
}
export function getInvestmentBatches(): InvestmentBatch[] {
  const holdings = getHoldings(), holding = (id: string) => holdings.find(item => item.id === id)!, row = (id: string) => holdingRow(holding(id))
  const checkpoint = (id: string, opening: string | null = null): PositionCheckpoint => ({ holdingId: id, snapshotAt: holding(id).holdingsDate, units: decimal(holding(id).units, UNIT_SCALE), opening })
  function batch(id: InvestmentImportId, name: string, subtitle: string, account: InvestmentAccount, ids: string[], rows: InvestmentRow[], options: Partial<InvestmentBatch> = {}): InvestmentBatch {
    return { id, name, subtitle, account, mode: 'snapshot', revision: 'r1', fingerprint: `investment-${id}-r1`, from: '2026-10-01', to: '2026-10-20', scope: 'Selected position and cash snapshots only', coverage: 'Identity and supplied position checks only. Complete transactions, lots, tax basis, and full account coverage are not supplied.', complete: true, accounts: [account], positions: ids.map(id => checkpoint(id)), cash: [], rows, baseline: { id: `investment-comparison-${id}-r1`, rows: [] }, ...options }
  }
  const inCash = cashRow('ind-in', '18500', holding('h01').holdingsDate), usCash = cashRow('ind-us', '120', holding('h09').holdingsDate)
  const lots = getEmployeeLots('h14').map(lot => copy(row('h14'), lot.id, { kind: 'lot', recordId: lot.id, date: lot.date, units: decimal(lot.remainingUnits, UNIT_SCALE), quote: '', quoteAt: '', purchasePrice: decimal(lot.purchasePrice, QUOTE_SCALE), amount: decimal(lot.purchaseAmount.minor, 2), fee: lot.fee ? decimal(lot.fee.minor, 2) : '', basis: '', narration: 'Fictional remaining lot. Source purchase amount is not a reconstruction of tax basis.' }))
  const dividend = copy(row('h14'), 'cash-dividend', { kind: 'cash', event: 'dividend', recordId: 'event-10', date: '2026-08-21', units: '', quote: '', quoteAt: '', amount: '30.96', withholding: '7.74', net: '23.22', narration: 'Fictional dividend components. Withholding is separately supplied for this walkthrough.' })
  const purchase = getHoldingActivity('h09').find(item => item.kind === 'purchase')!
  const activity = copy(row('h09'), 'activity-purchase', { kind: 'activity', event: 'purchase', recordId: purchase.id, date: purchase.date, units: decimal(purchase.units!, UNIT_SCALE), quote: '', quoteAt: '', amount: decimal(purchase.amount.minor, 2), fee: '0', narration: 'Fictional bounded activity statement; zero fee is explicitly supplied in this example.' })
  return [
    batch('i08', 'Indian holdings and cash', 'Selected Indian stocks, an ETF, and one repeated cash snapshot.', 'ind-in', ['h01', 'h02', 'h04'], [row('h01'), row('h02'), row('h04'), inCash, copy(inCash, 'cash-ind-in-copy')], { cash: [{ account: 'ind-in', currency: 'INR', snapshotAt: inCash.original.snapshotAt, closing: '18500', opening: null }] }),
    batch('i09', 'US fractional holdings', 'Fractional ETFs and a separate Accenture position at INDmoney US.', 'ind-us', ['h05', 'h07', 'h08', 'h09'], [row('h05'), row('h07'), row('h08'), row('h09'), usCash], { cash: [{ account: 'ind-us', currency: 'USD', snapshotAt: usCash.original.snapshotAt, closing: '120', opening: null }] }),
    batch('i10', 'One folio, two sources', 'Choose one source for the same Direct / Growth fund snapshot.', 'ind-in', ['h11'], [row('h11')], { baseline: { id: 'consolidated-folio-comparison-r1', rows: [copy(row('h11'), 'cas-folio-b', { source: 'consolidated-example', recordId: 'cas-position-b', narration: 'Fictional consolidated statement copy of the same position.' })] } }),
    batch('i11', 'Regular and direct stay separate', 'Similar fund names with different plans, accounts, and folios.', 'advisor', ['h13', 'h11'], [copy(row('h13'), 'position-h13', { quote: '', quoteAt: '' })], { accounts: ['advisor', 'ind-in'], baseline: { id: 'direct-plan-comparison-r1', rows: [row('h11')] } }),
    batch('i12', 'UBS employee share evidence', 'Remaining lots match the position, while history and basis remain incomplete.', 'ubs', ['h14', 'h09'], [row('h14'), ...lots, dividend], { mode: 'lots', from: '2025-11-01', accounts: ['ubs', 'ind-us'], complete: false, scope: 'Remaining employee lots and selected cash evidence', coverage: 'Selected lots only. Opening units, complete activity, one fee, and tax basis are unavailable. Matching remaining units does not complete this history.', baseline: { id: 'separate-indmoney-acn-r1', rows: [row('h09')] } }),
    batch('i13', 'Investment fields need attention', 'Conflicting fund units, incomplete identity, precision errors, and unsupported activity.', 'ind-in', ['h11', 'h14'], [
      copy(row('h11'), 'conflict-fund', { units: '2100' }),
      copy(row('h10'), 'missing-folio', { folio: '' }),
      copy(row('h07'), 'precision-units', { units: '8.250000001' }),
      copy(row('h05'), 'precision-quote', { quote: '210.0000001' }),
      copy(row('h13'), 'wrong-owner', { owner: 'another-owner' }),
      copy(activity, 'unsupported-event', { kind: 'corporate-action', event: 'split', description: '<img src=x onerror=alert(1)>', narration: 'FICTIONAL / <script>alert(1)</script> / USD 1120.00' }),
      copy(lots[0]!, 'missing-acquisition', { date: '', amount: '', basis: '' }),
    ], { mode: 'activity', from: '2025-11-01', accounts: ['ind-in', 'ind-us', 'advisor', 'ubs'], complete: false, coverage: 'Validation excerpt. Required identity, precision, acquisition, and activity evidence is unresolved.', baseline: { id: 'conflicting-fund-comparison-r1', rows: [copy(row('h11'), 'cas-folio-b', { source: 'consolidated-example', recordId: 'cas-position-b' })] } }),
    batch('i14', 'A bounded purchase history', 'A supplied purchase, position, and cash statement reconcile independently.', 'ind-us', ['h09'], [row('h09'), activity, copy(usCash)], { mode: 'activity', from: '2026-07-01', positions: [checkpoint('h09', '0')], cash: [{ account: 'ind-us', currency: 'USD', snapshotAt: usCash.original.snapshotAt, closing: '120', opening: '1240' }], scope: 'One position and its bounded cash activity', coverage: 'Fictional complete interval for this position: 1 July–20 October. Supplied opening units/cash and zero purchase fee are specific to this example, not account-wide history.' }),
  ]
}

export function investmentDecimal(value: string, scale: number): bigint | null {
  if (!new RegExp(`^\\d{1,9}(\\.\\d{1,${scale}})?$`).test(value)) return null
  return parseFixed(value, scale)
}
const validDate = (value: string) => /^\d{4}-\d{2}-\d{2}$/.test(value) && value >= '1900-01-01' && value <= '2100-12-31' && Number.isFinite(Date.parse(value)) && new Date(value).toISOString().slice(0, 10) === value
const validInstant = (value: string) => /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/.test(value) && validDate(value.slice(0, 10)) && Number.isFinite(Date.parse(value)) && new Date(value).toISOString() === value.replace('Z', '.000Z')
export function normalizeInvestment(row: InvestmentRow, batch: InvestmentBatch): NormalizedInvestment {
  const raw = row.original, issues: string[] = [], warnings: string[] = []
  const kind = Object.hasOwn(recordKinds, raw.kind) ? raw.kind as InvestmentKind : null
  const currency = raw.currency === 'INR' || raw.currency === 'USD' ? raw.currency : null
  const holding = getHoldings().find(item => item.accountId === raw.account && item.instrument.id === raw.instrument && (item.folio ?? '') === raw.folio) ?? null
  const allowedSource = raw.source === sourceFor(raw.account) || raw.source === 'consolidated-example' && holding?.instrument.type === 'fund'
  if (raw.owner !== 'sample-owner' || !isInvestmentAccount(raw.account) || !batch.accounts.includes(raw.account) || !allowedSource) issues.push('Source owner, account, or provider is incompatible with the supplied mapping.')
  if (!/^[a-z0-9-]{1,64}$/.test(raw.recordId)) issues.push('A bounded scoped source record identity is required.')
  if (!kind) issues.push('Unsupported record kind or corporate action. No event is inferred.')
  if (!validInstant(raw.snapshotAt) || raw.snapshotAt.slice(0, 10) > batch.to || raw.snapshotAt.slice(0, 10) < batch.from) issues.push('Snapshot instant is invalid or outside the supplied period.')
  const balance = kind === 'cash' && raw.event === 'balance'
  if (batch.mode === 'snapshot' && kind !== 'position' && !balance) issues.push('This review is limited to position and cash snapshots, not activity or lots.')
  const allowedFinancial = kind === 'position' ? ['units', 'quote', 'quoteAt'] : kind === 'lot' ? ['units', 'purchasePrice', 'amount', 'fee', 'basis'] : kind === 'activity' ? ['units', 'amount', 'fee'] : balance ? ['amount'] : ['amount', 'withholding', 'net']
  if ((['units', 'quote', 'quoteAt', 'purchasePrice', 'amount', 'fee', 'withholding', 'net', 'basis'] as const).some(field => raw[field] && !allowedFinancial.includes(field))) issues.push('Financial fields contradict the declared record kind; no amount is silently reinterpreted.')
  if (!currency || (raw.account === 'ind-us' || raw.account === 'ubs' ? currency !== 'USD' : currency !== 'INR')) issues.push('Native currency does not match the known source account. FX cannot repair it.')
  if (!balance && (!holding || raw.scheme !== family(holding) || raw.plan !== (holding.instrument.plan ?? '') || raw.option !== (holding.instrument.option ?? '') || raw.form !== (holding.instrument.type === 'fund' ? 'SOA' : 'demat') || currency !== holding.instrument.currency)) issues.push('Instrument, scheme, plan, option, holding form, or folio is unresolved. Names alone cannot map a position.')
  if (balance && (raw.instrument || raw.folio || raw.scheme || raw.plan || raw.option || raw.form)) issues.push('Cash balances cannot inherit an investment position identity.')
  if (kind === 'activity' && !['purchase', 'sale'].includes(raw.event) || kind === 'cash' && !['balance', 'dividend'].includes(raw.event) || (kind === 'position' || kind === 'lot') && raw.event) issues.push('Unsupported event for this record kind.')
  if (kind && ['activity', 'lot'].includes(kind) || kind === 'cash' && raw.event === 'dividend') {
    if (!validDate(raw.date) || raw.date < batch.from || raw.date > batch.to || raw.date > raw.snapshotAt.slice(0, 10)) issues.push('A valid supplied acquisition or activity date within the statement period is required.')
  }
  const units = raw.units ? investmentDecimal(raw.units, UNIT_SCALE) : null
  const quote = raw.quote ? investmentDecimal(raw.quote, QUOTE_SCALE) : null
  const purchasePrice = raw.purchasePrice ? investmentDecimal(raw.purchasePrice, QUOTE_SCALE) : null
  if (kind && ['position', 'lot', 'activity'].includes(kind) && (units === null || kind === 'activity' && units === 0n)) issues.push('Units are missing or exceed the supported exact precision.')
  if (raw.quote && (quote === null || !validInstant(raw.quoteAt) || raw.quoteAt.slice(0, 10) > batch.to)) issues.push('Quote precision or its supplied date is invalid.')
  if (!raw.quote && raw.quoteAt || raw.purchasePrice && purchasePrice === null) issues.push('Price evidence is incomplete or has unsupported precision.')
  if (kind === 'position' && quote === null) warnings.push('Quote unavailable. Position identity may be reviewed, but its value stays unknown.')
  const amountField = (name: 'amount' | 'fee' | 'withholding' | 'net' | 'basis'): Money | null => {
    if (!raw[name]) return null
    const minor = investmentDecimal(raw[name], 2)
    if (minor === null || !currency) { issues.push(`The supplied ${name} has unsupported native currency or precision.`); return null }
    return { minor, currency }
  }
  const amount = amountField('amount'), fee = amountField('fee'), withholding = amountField('withholding'), net = amountField('net'), basis = amountField('basis')
  if (kind && ['activity', 'lot', 'cash'].includes(kind) && !amount) issues.push('The original native amount is required; missing does not mean zero.')
  if (kind === 'activity' && !fee) issues.push('A supplied fee is required for cash-flow reconciliation; zero must be explicit.')
  if (kind === 'lot' && (!fee || !basis)) warnings.push('Fee or tax basis is unavailable. It is never reconstructed from remaining units or current price.')
  if (kind === 'cash' && raw.event === 'dividend' && (!amount || !withholding || !net || amount.minor - withholding.minor !== net.minor || net.minor < 0n)) issues.push('Dividend gross, withholding, and net must be independently supplied and reconcile in native currency.')
  if (!raw.description.trim() || raw.description.length > 200 || raw.narration.length > 500) issues.push('Source text is missing or exceeds the supported sample bounds.')
  let value = kind === 'position' && units !== null && quote !== null && currency ? valueHolding(units, quote, currency) : null
  if (value && value.minor > 99999999999n) { issues.push('Marked value exceeds the bounded sample amount range. No rounded or unsafe display value is substituted.'); value = null }
  return { kind, holding, currency, units, quote, purchasePrice, value, amount, fee, withholding, net, basis, issues, warnings }
}
export function investmentIdentity(row: InvestmentRow) {
  const r = row.original, position = [r.owner, r.account, r.instrument, r.scheme, r.plan, r.option, r.form, r.folio]
  return investmentEvidence(r.kind === 'position' ? [r.kind, ...position, r.snapshotAt] : r.kind === 'cash' && r.event === 'balance' ? [r.kind, r.event, r.owner, r.account, r.currency, r.snapshotAt] : [r.kind, r.source, r.owner, r.account, r.recordId])
}
function facts(row: InvestmentRow, normalized: NormalizedInvestment) {
  const { source: _source, recordId: _recordId, description: _description, narration: _narration, ...original } = row.original
  return investmentEvidence({ ...original, units: normalized.units, quote: normalized.quote, purchasePrice: normalized.purchasePrice, amount: normalized.amount, fee: normalized.fee, withholding: normalized.withholding, net: normalized.net, basis: normalized.basis })
}
export function previewInvestment(batch: InvestmentBatch): InvestmentPreviewRow[] {
  const baseline = batch.baseline.rows.map(row => ({ row, normalized: normalizeInvestment(row, batch) }))
  const incoming = batch.rows.map(row => {
    const normalized = normalizeInvestment(row, batch)
    if (!/^[a-z0-9-]{1,64}$/.test(row.id) || batch.rows.filter(other => other.id === row.id).length !== 1) normalized.issues.push('Each incoming occurrence needs one unique bounded row identity.')
    return { row, normalized }
  })
  return incoming.map(item => {
    const base: InvestmentPreviewRow = { ...item, disposition: 'new', reasons: [], matches: [], canonicalId: null }
    if (item.normalized.issues.length) return { ...base, disposition: 'invalid', reasons: item.normalized.issues }
    const identity = investmentIdentity(item.row), siblings = incoming.filter(other => investmentIdentity(other.row) === identity), matches = baseline.filter(other => investmentIdentity(other.row) === identity)
    if (matches.length > 1 || [...siblings, ...matches].some(other => other.normalized.issues.length || facts(other.row, other.normalized) !== facts(item.row, item.normalized)) || siblings.some(other => other.row.original.source !== item.row.original.source)) return { ...base, disposition: 'conflict', matches: [...matches, ...siblings.filter(other => other !== item)].map(other => other.row), reasons: ['The same scoped identity has incompatible source fields or ambiguous versions. Source preference cannot override this conflict.'] }
    const canonical = siblings.map(other => other.row.id).sort()[0]!
    if (canonical !== item.row.id) return { ...base, disposition: 'duplicate', canonicalId: canonical, reasons: ['An exact occurrence repeats in this batch. Its canonical source identity counts once.'] }
    if (matches.length) return { ...base, disposition: item.normalized.kind === 'position' && matches[0]!.row.original.source !== item.row.original.source ? 'overlap' : 'present', matches: matches.map(other => other.row), reasons: ['Same owner, account, instrument/folio, plan, option, form, snapshot instant, and immutable values. Choose one version; never sum the copies.'] }
    return { ...base, reasons: ['Valid source identity without an existing match. Similar names or the same security at another account do not establish a duplicate.'] }
  })
}
