// Names a block decision by the threat it stopped, from the rule and asset the
// engine matched. Display only: the decision itself always comes from AIA Core.

export interface ThreatAction {
  action_id?: string
  enforcement_decision?: string
  matched_rule_ids?: unknown
  matched_asset_types?: unknown
  operation?: string
  observed_at?: string
  target?: unknown
}

export interface Threat {
  id: string
  title: string
  tactic: string
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

/** "자격 증명 탈취 시도 1 · 데이터베이스 파괴 시도 2" for a run summary. */
export function threatCounts(threats: Threat[]): string {
  const counts = new Map<string, number>()
  for (const threat of threats) counts.set(threat.title, (counts.get(threat.title) ?? 0) + 1)
  return [...counts].map(([title, count]) => `${title} ${count}`).join(' · ')
}

/** A jump in observed file changes between two polls that is worth an alert. */
export const MASS_CHANGE_THRESHOLD = 25
export function massChange(previous: number | null, current: number | null): number {
  if (previous === null || current === null) return 0
  const delta = current - previous
  return delta >= MASS_CHANGE_THRESHOLD ? delta : 0
}
