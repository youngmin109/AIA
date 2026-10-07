/** Codex connectors (MCP servers) in display form (EPIC-021 TASK-117). Read-only. */
export interface CodexConnector {
  name: string
  status: string
  auth: string
  tool_count: number
  tools: string[]
  error: string | null
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

/** "연결됨 · 로그인됨 · 도구 2개"; unknown login states are left out. */
export function connectorSummary(connector: CodexConnector): string {
  const auth = AUTH_LABEL[connector.auth]
  return [connectorStatusLabel(connector.status), auth, `도구 ${connector.tool_count}개`].filter(Boolean).join(' · ')
}

export function connectorTone(connector: CodexConnector): 'ok' | 'warn' | 'neutral' {
  if (connector.status === 'connected') return 'ok'
  if (connector.status === 'failed' || connector.status === 'authenticationRequired') return 'warn'
  return 'neutral'
}
