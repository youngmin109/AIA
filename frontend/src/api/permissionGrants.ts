/** What Codex asked to widen and what the user granted (EPIC-022 TASK-107). */
export interface PermissionEntry { access: 'read' | 'write' | 'deny'; target: string; scope: 'inside' | 'outside' | 'unknown' }
export interface PermissionGrant {
  granted_at: string
  scope: 'turn' | 'session' | 'mode_change_request'
  network: boolean | null
  mode?: string
  filesystem: PermissionEntry[]
  reason?: string
}

export const ACCESS_LABEL: Record<PermissionEntry['access'], string> = { read: '읽기', write: '쓰기', deny: '막기' }
export const SCOPE_NOTE: Record<PermissionEntry['scope'], string> = {
  inside: '작업 폴더 안',
  outside: 'AIA 기준점·복구 범위 밖',
  unknown: '범위 확인 불가',
}
export const GRANT_SCOPE_LABEL: Record<PermissionGrant['scope'], string> = { turn: '이번 요청만', session: '실행 내내', mode_change_request: '권한 변경 요청' }

/** One short line per grant, e.g. "인터넷 · 쓰기 C:\shared · 실행 내내". */
export function grantSummary(grant: Pick<PermissionGrant, 'network' | 'filesystem'> & { scope?: PermissionGrant['scope']; mode?: string }): string {
  if (grant.scope === 'mode_change_request') {
    const name = grant.mode === 'full_access' ? '전체 권한' : grant.mode === 'auto_review' ? '나 대신 승인' : '권한 변경'
    return `${name} 요청 · 실제 적용은 별도 확인 필요`
  }
  const parts = [
    ...(grant.network ? ['인터넷'] : []),
    ...grant.filesystem.filter(entry => entry.access !== 'deny').map(entry => `${ACCESS_LABEL[entry.access]} ${entry.target}`),
  ]
  const what = parts.length ? parts.join(' · ') : '추가 권한 없음'
  return grant.scope ? `${what} · ${GRANT_SCOPE_LABEL[grant.scope]}` : what
}

/** True when a grant reaches beyond what AIA's checkpoint and watchers cover. */
export function widensBeyondProtection(grants: PermissionGrant[] | null | undefined): boolean {
  return (grants ?? []).some(grant => grant.scope === 'mode_change_request' || grant.network || grant.filesystem.some(entry => entry.access !== 'deny' && entry.scope !== 'inside'))
}
