// Names a block decision by the threat it stopped, from the rule and asset the
// engine matched. Display only: the decision itself always comes from AIA Core.

export interface ThreatAction {
  action_id?: string
  enforcement_decision?: string
  enforcement_reasons?: unknown
  matched_rule_ids?: unknown
  matched_asset_types?: unknown
  operation?: string
  observed_at?: string
  policy_decision?: string
  target?: unknown
}

export interface Threat {
  id: string
  title: string
  tactic: string
  target: string | null
  at: string | null
}

export interface MissedViolation {
  id: string
  title: string
  reason: string
  target: string | null
  at: string | null
}

const PROTECTED_FILE: [string, string] = ['보호 파일 파괴 시도', '데이터 파괴']
const BY_ASSET: Record<string, [string, string]> = {
  SECRET: ['자격 증명 탈취 시도', '자격 증명 접근'],
  DATABASE_RELATED: ['데이터베이스 파괴 시도', '데이터 파괴'],
  REPOSITORY: ['작업 내용 파괴 시도', '데이터 파괴'],
  WORKSPACE: ['대량 삭제·강제 종료 시도', '데이터 파괴'],
  DEPENDENCY: ['의존성 파일 변조 시도', '공급망'],
  INFRASTRUCTURE: ['배포 설정 변조 시도', '공급망'],
}
const OTHER: [string, string] = ['정책 위반 시도', '정책 위반']

const strings = (value: unknown): string[] => Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : []

/** A readable path for the alert; command fingerprints are hashes and stay hidden. */
function targetLabel(target: unknown): string | null {
  if (!target || typeof target !== 'object') return null
  const display = (target as { display?: unknown }).display
  if (typeof display !== 'string' || display === '—' || /^(sha256|fingerprint)[:-]/i.test(display) || /^[0-9a-f]{32,}$/i.test(display)) return null
  return display
}

/** The runtime action view carries file targets as canonical_path, not display. */
function missedViolationTargetLabel(target: unknown): string | null {
  const display = targetLabel(target)
  if (display) return display
  if (!target || typeof target !== 'object') return null
  const value = target as { canonical_path?: unknown; target_kind?: unknown }
  const path = value.canonical_path
  if (value.target_kind !== 'FILE' && value.target_kind !== 'DIRECTORY') return null
  if (typeof path !== 'string' || !path || path === '—' || /^(sha256|fingerprint)[:-]/i.test(path) || /^[0-9a-f]{32,}$/i.test(path)) return null
  return path
}

/** The threat a CONTAIN decision stopped, or null for anything that was not blocked. */
export function threatOf(action: ThreatAction, index = 0): Threat | null {
  if (action.enforcement_decision !== 'CONTAIN') return null
  const rules = strings(action.matched_rule_ids)
  const assets = strings(action.matched_asset_types)
  const [title, tactic] = rules.some(rule => rule.startsWith('aia-user-protected-path'))
    ? PROTECTED_FILE
    : BY_ASSET[assets.find(asset => asset in BY_ASSET) ?? ''] ?? OTHER
  return { id: action.action_id ?? `threat-${index}`, title, tactic, target: targetLabel(action.target), at: action.observed_at ?? null }
}

/** Every blocked threat of a run, in the order AIA decided them. */
export function threatsOf(actions: ThreatAction[] | null | undefined): Threat[] {
  return (actions ?? []).flatMap((action, index) => threatOf(action, index) ?? [])
}

const MISSED_VIOLATION_REASON: Record<string, string> = {
  SENSOR_UNHEALTHY: '감시 장치 하나가 정상이 아니었어요',
  ATTRIBUTION_NOT_EXACT: '이 요청이 보호 중인 Codex에서 왔다는 걸 확신하지 못했어요',
  AUDIT_MODE_NO_AUTOMATIC_ENFORCEMENT: '기록 모드라서 막지 않고 기록만 했어요',
  HOOK_TRUST_UNAVAILABLE: 'Hook 신뢰를 확인하지 못했어요',
  WORKSPACE_LEASE_INVALID: '작업 폴더 잠금을 확인하지 못했어요',
  WORKSPACE_LEASE_UNVERIFIABLE: '작업 폴더 잠금을 확인하지 못했어요',
  ROOT_PROCESS_IDENTITY_INVALID: 'AIA가 띄운 Codex가 맞는지 확인하지 못했어요',
  ROOT_REGISTRATION_MISMATCH: 'AIA가 띄운 Codex가 맞는지 확인하지 못했어요',
  PROCESS_IDENTITY_MISMATCH: 'AIA가 띄운 Codex가 맞는지 확인하지 못했어요',
  LAUNCH_PROVENANCE_INVALID: 'AIA가 띄운 Codex가 맞는지 확인하지 못했어요',
  SESSION_NOT_RUNNING: '실행이 끝나가는 중이었어요',
}
const AUDIT_MODE_REASON = 'AUDIT_MODE_NO_AUTOMATIC_ENFORCEMENT'
const MISSED_VIOLATION_FALLBACK = '막을 조건을 확인하지 못했어요'

/** A policy violation the gate did not contain, with only its safe reason codes. */
export function missedViolationOf(action: ThreatAction, index = 0): MissedViolation | null {
  if (action.policy_decision !== 'VIOLATION' || action.enforcement_decision === 'CONTAIN') return null
  const codes = strings(action.enforcement_reasons)
  const reason = codes.length
    ? codes.map(code => (MISSED_VIOLATION_REASON[code] ?? MISSED_VIOLATION_FALLBACK) + ' (' + code + ')').join(' · ')
    : MISSED_VIOLATION_FALLBACK
  return {
    id: action.action_id ?? 'missed-violation-' + index,
    title: codes.includes(AUDIT_MODE_REASON) ? '정책 위반 기록 · 막지 않음' : '정책 위반 감지 · 막지 못함',
    reason,
    target: missedViolationTargetLabel(action.target),
    at: action.observed_at ?? null,
  }
}

/** Every policy violation the gate did not contain, in action order. */
export function missedViolationsOf(actions: ThreatAction[] | null | undefined): MissedViolation[] {
  return (actions ?? []).flatMap((action, index) => missedViolationOf(action, index) ?? [])
}

/** "자격 증명 탈취 시도 1 · 데이터베이스 파괴 시도 2" for a run summary. */
export function threatCounts(threats: Threat[]): string {
  const counts = new Map<string, number>()
  for (const threat of threats) counts.set(threat.title, (counts.get(threat.title) ?? 0) + 1)
  return [...counts].map(([title, count]) => `${title} ${count}`).join(' · ')
}

/** A protected file the file sensor saw change while the run was live (not a block). */
export interface ProtectedChange { path: string; event_type: string; observed_at?: string; evidence_id?: string }
const CHANGE_LABEL: Record<string, string> = { created: '생성', modified: '수정', deleted: '삭제', moved: '이동' }
export function changeLabel(eventType: string): string {
  return CHANGE_LABEL[eventType] ?? eventType
}

/** The newest protected change to announce, only when the count grew since the last poll. */
export function newProtectedChange(previous: number | null, current: number | null, changes: ProtectedChange[] | undefined): ProtectedChange | null {
  if (previous === null || current === null || current <= previous) return null
  return changes?.[0] ?? null
}

/** A jump in observed file changes between two polls that is worth an alert. */
export const MASS_CHANGE_THRESHOLD = 25
export function massChange(previous: number | null, current: number | null): number {
  if (previous === null || current === null) return 0
  const delta = current - previous
  return delta >= MASS_CHANGE_THRESHOLD ? delta : 0
}
