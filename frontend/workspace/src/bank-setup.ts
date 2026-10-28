export type BankSetupPath = '/bank-account-setup/query' | '/bank-account-setup/create'
export type BankSetupInstitution = 'hdfc' | 'sbi'
export type BankSetupCurrency = 'INR' | 'USD'
export type BankSetupInput = Readonly<{ institution: BankSetupInstitution; label: string; currencies: readonly BankSetupCurrency[] }>
export type BankSetupCommand = BankSetupInput & Readonly<{ intent_id: string; expected_revision: number }>
export type BankSetupReceipt = BankSetupInput & Readonly<{ intent_id: string; revision: number; account_id: string }>
export type BankSetupSnapshot = Readonly<{ revision: number; last_saved: BankSetupReceipt | null }>
export const MAX_BANK_SETUP_REVISION = 1000
export const BANK_SETUP_LABEL_PATTERN = '^[A-Za-z][A-Za-z .()-]{0,63}$'
const labelPattern = new RegExp(BANK_SETUP_LABEL_PATTERN)
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/
const identifier = (value: unknown): value is string => typeof value === 'string' && value.length === 36 && uuid.test(value) && value !== '00000000-0000-0000-0000-000000000000'
const object = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value)
const exact = (value: Record<string, unknown>, keys: string[]) => Object.keys(value).length === keys.length && Object.keys(value).every(key => keys.includes(key))
const revision = (value: unknown, minimum: number): value is number => Number.isSafeInteger(value) && Number(value) >= minimum && Number(value) <= MAX_BANK_SETUP_REVISION
function invalid(): never { throw new Error('Bank account setup could not be verified.') }

export function bankSetupInput(value: unknown): BankSetupInput {
  if (!object(value) || !exact(value, ['institution', 'label', 'currencies']) || (value.institution !== 'hdfc' && value.institution !== 'sbi') || typeof value.label !== 'string' || !labelPattern.test(value.label) || /[^A-Za-z .()-]/.test(value.label) || !Array.isArray(value.currencies)) invalid()
  const currencies = value.currencies
  if (!(currencies.length === 1 && (currencies[0] === 'INR' || currencies[0] === 'USD') || currencies.length === 2 && currencies[0] === 'INR' && currencies[1] === 'USD')) invalid()
  return Object.freeze({ institution: value.institution, label: value.label, currencies: Object.freeze([...currencies]) })
}

export function bankSetupCommand(intent_id: string, expected_revision: number, input: BankSetupInput): BankSetupCommand {
  if (!identifier(intent_id) || !revision(expected_revision, 0)) invalid()
  return Object.freeze({ intent_id, expected_revision, ...bankSetupInput(input) })
}

export function parseBankSetupReceipt(value: unknown, command?: BankSetupCommand): BankSetupReceipt {
  if (!object(value) || !exact(value, ['intent_id', 'revision', 'account_id', 'institution', 'label', 'currencies']) || !identifier(value.intent_id) || !identifier(value.account_id) || !revision(value.revision, 1)) invalid()
  const input = bankSetupInput({ institution: value.institution, label: value.label, currencies: value.currencies })
  if (command && (value.intent_id !== command.intent_id || value.revision !== command.expected_revision + 1 || input.institution !== command.institution || input.label !== command.label || input.currencies.join(',') !== command.currencies.join(','))) invalid()
  return Object.freeze({ intent_id: value.intent_id, revision: value.revision, account_id: value.account_id, ...input })
}

export function parseBankSetupSnapshot(value: unknown): BankSetupSnapshot {
  if (!object(value) || !exact(value, ['revision', 'last_saved']) || !revision(value.revision, 0)) invalid()
  const last_saved = value.last_saved === null ? null : parseBankSetupReceipt(value.last_saved)
  if (value.revision === 0 ? last_saved !== null : last_saved === null || last_saved.revision !== value.revision) invalid()
  return Object.freeze({ revision: value.revision, last_saved })
}
