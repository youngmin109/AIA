/**
 * A session UUID is an internal correlation key, not a useful name for a
 * person.  The UI therefore uses the agent and Workspace as the visible
 * session label.  The UUID stays in the API and audit evidence unchanged.
 */
export function workspaceShortName(workspace?: string | null): string {
  if (!workspace) return '작업공간 확인 중'

  const parts = workspace.replace(/[\\/]+$/, '').split(/[\\/]/).filter(Boolean)
  return parts.at(-1) || workspace
}

export function sessionDisplayName(workspace?: string | null): string {
  return `Codex · ${workspaceShortName(workspace)}`
}

export function sessionShortId(sessionId: string): string {
  return `#${sessionId.slice(0, 8)}`
}

export function sessionCreatedLabel(createdAt?: string): string {
  if (!createdAt) return '시작 시각 확인 중'
  const date = new Date(createdAt)
  if (Number.isNaN(date.getTime())) return '시작 시각 확인 중'
  return new Intl.DateTimeFormat('ko-KR', {
    month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false,
  }).format(date)
}
