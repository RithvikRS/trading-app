export type DisplayPreferences = { theme: 'light' | 'dark'; display_currency: 'INR' | 'USD'; amount_masked: boolean }
export type PreferenceSnapshot = DisplayPreferences & { revision: number }
export type PreferenceStatus = 'idle' | 'saving' | 'saved' | 'conflict'

export function systemTheme(): 'light' | 'dark' {
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

export function parsePreferences(data: Record<string, unknown>): PreferenceSnapshot {
  if (Object.keys(data).length !== 4 || !Object.keys(data).every(key => ['theme', 'display_currency', 'amount_masked', 'revision'].includes(key)) || typeof data.theme !== 'string' || !['light', 'dark'].includes(data.theme) || typeof data.display_currency !== 'string' || !['INR', 'USD'].includes(data.display_currency) || typeof data.amount_masked !== 'boolean' || !Number.isSafeInteger(data.revision) || Number(data.revision) < 0) throw new Error('Invalid preference response.')
  const result = data as PreferenceSnapshot
  if (result.revision === 0) {
    if (result.theme !== 'light' || result.display_currency !== 'INR' || !result.amount_masked) throw new Error('Invalid preference defaults.')
    return { ...result, theme: systemTheme() }
  }
  return result
}
