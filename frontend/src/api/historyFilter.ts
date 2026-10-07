import type { RunSummary } from './types'
import { isRunActive, stoppedWhilePreparing } from './sessionNavigation.ts'

export type HistoryFilter = 'all' | 'review' | 'ok'
export type HistoryState = 'live' | 'review' | 'ok' | 'failed' | 'orphaned'

const ENDED = new Set(['COMPLETED', 'ABORTED', 'FAILED'])

/** Display grouping only: a run "needs review" when it has incidents or its record is not verified. */
export function historyState(run: RunSummary): HistoryState {
  const orphaned = Boolean((run.runtime_reconciliation as { orphaned?: boolean } | undefined)?.orphaned)
  if (orphaned) return 'orphaned'
  if (isRunActive(run)) return 'live'
  if (run.status === 'FAILED') return 'failed'
  if ((run.incident_count ?? 0) > 0 || (ENDED.has(String(run.status)) && run.bundle_status !== 'VALID')) return 'review'
  return 'ok'
}

export function filterRuns(runs: RunSummary[], filter: HistoryFilter): RunSummary[] {
  if (filter === 'all') return runs
  return runs.filter(run => {
    const state = historyState(run)
    return filter === 'ok' ? state === 'ok' : state === 'review' || state === 'failed' || state === 'orphaned'
  })
}

export const HISTORY_STATE_LABEL: Record<HistoryState, string> = {
  live: '실행 중',
  review: '확인 필요',
  ok: '정상',
  failed: '실패',
  orphaned: '연결 끊김',
}

/** Row label; a run stopped while preparing says so instead of a generic lost connection. */
export function historyStateLabel(run: RunSummary): string {
  return stoppedWhilePreparing(run) ? '준비 중 중단' : HISTORY_STATE_LABEL[historyState(run)]
}
