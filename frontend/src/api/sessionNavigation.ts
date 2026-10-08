import type { RunSummary } from './types'
import { isSessionRunning } from './display.ts'

const PREPARING_STATUSES = ['CREATED', 'PREPARING', 'PROTECTING', 'STARTING', 'READY']

/**
 * The app closed while AIA was still preparing: reconciliation verified that
 * no Agent was ever started.  Display only; the stored run status is kept.
 */
export function stoppedWhilePreparing(run: RunSummary): boolean {
  const reconciliation = run.runtime_reconciliation as { orphaned?: boolean; agent_process_status?: string } | undefined
  return Boolean(reconciliation?.orphaned) && reconciliation?.agent_process_status === 'NOT_STARTED' && PREPARING_STATUSES.includes(run.status ?? '')
}

export function isRunActive(run: RunSummary): boolean {
  const reconciliation = run.runtime_reconciliation as { orphaned?: boolean } | undefined
  return isSessionRunning(run.status, Boolean(reconciliation?.orphaned))
}

/** Hook connection checks are real protected runs: audit and reports keep them, the sidebar does not. */
export function isHookVerificationRun(run: RunSummary): boolean {
  return /[\\/]aia-hook-verify-[^\\/]*$/i.test(String(run.workspace ?? ''))
}

/** Keep completed sessions discoverable, without pretending they are live. */
export function sidebarSessions(runs: RunSummary[], selectedId: string | null, limit = 10): RunSummary[] {
  const unique = [...new Map(runs.filter(run => !isHookVerificationRun(run)).map(run => [run.session_id, run])).values()]
  const sorted = unique.sort((a, b) => {
    const activeOrder = Number(isRunActive(b)) - Number(isRunActive(a))
    const time = (run: RunSummary) => Date.parse(run.created_at ?? '') || 0
    return activeOrder || time(b) - time(a) || a.session_id.localeCompare(b.session_id)
  })
  const visible = sorted.slice(0, limit)
  const selected = unique.find(run => run.session_id === selectedId)
  if (selected && !visible.some(run => run.session_id === selectedId) && limit > 0) visible[visible.length - 1] = selected
  return visible
}

export function sessionDestination(run: RunSummary): 'work' | 'history' {
  // Orphaned sessions cannot be reattached as a live app-server conversation.
  return isRunActive(run) ? 'work' : 'history'
}

export function sessionStateLabel(run: RunSummary): string {
  const reconciliation = run.runtime_reconciliation as { orphaned?: boolean } | undefined
  if (stoppedWhilePreparing(run)) return '준비 중 중단'
  if (reconciliation?.orphaned) return '연결 끊김 · 기록 확인'
  if (run.status === 'READY') return '입력 준비 완료'
  if (run.status === 'RUNNING') return '실행 중'
  if (['CREATED', 'PREPARING', 'PROTECTING', 'STARTING'].includes(run.status ?? '')) return '준비 중'
  return ({ COMPLETED: '종료됨', ABORTED: '사용자 중지', FAILED: '실행 실패' } as Record<string, string>)[run.status ?? ''] ?? '상태 확인 필요'
}
