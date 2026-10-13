/** Codex connectors (MCP servers) in display form (EPIC-022 TASK-117). Read-only. */
export interface CodexConnector {
  name: string
  status: string
  auth: string
  tool_count: number
  tools: string[]
  error: string | null
  /** Turned off for this protected run (Settings > 외부 도구). */
  turned_off_by_aia?: boolean
}

const STATUS_LABEL: Record<string, string> = {
  connected: '연결됨',
  starting: '시작 중',
  notStarted: '시작 전',
  authenticationRequired: '로그인 필요',
  failed: '실패',
  cancelled: '취소됨',
  disabled: '꺼짐',
}

const AUTH_LABEL: Record<string, string> = {
  oAuth: '로그인됨',
  bearerToken: '토큰 사용',
  notLoggedIn: '로그인 안 됨',
  unsupported: '로그인 없음',
}

export function connectorStatusLabel(status: string): string {
  return STATUS_LABEL[status] ?? '상태 확인 불가'
}

/** "연결됨 · 로그인됨 · 도구 2개"; unknown login states, and a status Codex did not report, are left out. */
export function connectorSummary(connector: CodexConnector): string {
  if (connector.turned_off_by_aia) return '보호 실행에서 꺼 둠'
  const auth = AUTH_LABEL[connector.auth]
  const status = connector.status === 'unknown' ? null : connectorStatusLabel(connector.status)
  return [status, auth, `도구 ${connector.tool_count}개`].filter(Boolean).join(' · ')
}

/** Tools still on first; the ones AIA turned off for this run after them. */
export function connectorsOnFirst(connectors: CodexConnector[]): CodexConnector[] {
  return [...connectors].sort((a, b) => Number(Boolean(a.turned_off_by_aia)) - Number(Boolean(b.turned_off_by_aia)))
}

export function connectorTone(connector: CodexConnector): 'ok' | 'warn' | 'neutral' {
  if (connector.status === 'connected') return 'ok'
  if (connector.status === 'failed' || connector.status === 'authenticationRequired') return 'warn'
  return 'neutral'
}
