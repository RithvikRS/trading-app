import { bankComparison } from './bank-comparison-evidence'
import type { BankProvenance } from './bank-provenance'
import type { NativeComparison } from './comparison-evidence'
import { emptyInputProgress, inputPage } from './input-evidence'
import type { InputPage, InputProgress, InputSelection } from './input-evidence'
import type { SavedReceipt } from './receipt-evidence'

export function bankInputPage(value: unknown, comparison: NativeComparison, receipt: SavedReceipt, context: BankProvenance, selection: InputSelection, after: string | null = null, preceding: InputProgress = emptyInputProgress): InputPage {
  const valid = bankComparison(comparison, comparison.scope, receipt, context)
  return inputPage(value, valid, receipt, context.origin, selection, after, preceding)
}
