export type ConnectionSnapshot = { status: 'disconnected' | 'pending' | 'authorized' | 'refreshing' | 'reconnect_required'; can_complete: boolean; expires_at: string | null; financial_access_enabled: false }
export type ConnectionState = { kind: 'ready'; value: ConnectionSnapshot; cleanup?: 'confirmed' | 'unavailable' | 'not_needed' } | { kind: 'loading' | 'failed' | 'unconfigured' }
export type ConnectionAction = 'status' | 'authorize' | 'complete' | 'refresh' | 'disconnect'
const invalid = () => new Error('Invalid connection response.')
export function parseConnection(data: Record<string, unknown>): ConnectionSnapshot {
  if (Object.keys(data).length !== 4 || !['disconnected', 'pending', 'authorized', 'refreshing', 'reconnect_required'].includes(String(data.status)) || typeof data.can_complete !== 'boolean' || data.financial_access_enabled !== false || !(data.expires_at === null || typeof data.expires_at === 'string' && /^\d{4}-\d\d-\d\dT[\d:.]+(?:Z|\+00:00)$/.test(data.expires_at) && Number.isFinite(Date.parse(data.expires_at)))) throw invalid()
  return data as ConnectionSnapshot
}
export function authorizationTarget(data: Record<string, unknown>): string {
  if (Object.keys(data).length !== 1 || typeof data.authorization_url !== 'string' || data.authorization_url.length > 4096) throw invalid()
  const url = new URL(data.authorization_url)
  const required = ['response_type', 'client_id', 'redirect_uri', 'scope', 'state', 'code_challenge', 'code_challenge_method', 'resource']
  if (url.origin !== 'https://mcp.indmoney.com' || url.pathname !== '/authorize' || url.username || url.password || url.hash || [...url.searchParams.keys()].length !== required.length || required.some(key => url.searchParams.getAll(key).length !== 1) || url.searchParams.get('response_type') !== 'code' || url.searchParams.get('scope') !== 'portfolio:read' || url.searchParams.get('resource') !== 'https://mcp.indmoney.com/mcp' || url.searchParams.get('redirect_uri') !== 'https://127.0.0.1:8443/api/v1/connections/indmoney/callback' || url.searchParams.get('code_challenge_method') !== 'S256' || !/^[\x21-\x7e]{1,256}$/.test(url.searchParams.get('client_id') ?? '') || ['state', 'code_challenge'].some(key => !/^[A-Za-z0-9_-]{43}$/.test(url.searchParams.get(key) ?? ''))) throw invalid()
  return url.href
}
