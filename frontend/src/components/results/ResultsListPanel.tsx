import { useShellStore } from '../../state/shellStore'
import { useRunList } from '../../hooks/useRunList'
import type { RunSummary } from '../../api/types'

const COMPLETED_STATUSES = new Set(['COMPLETED', 'ABORTED', 'FAILED'])

function toneFor(bundleStatus: string | undefined): 'ok' | 'warn' | 'bad' {
  const upper = String(bundleStatus || '').toUpperCase()
  if (upper === 'VALID') return 'ok'
  if (upper === 'INVALID') return 'bad'
  return 'warn'
}

function shortId(sessionId: string): string {
  return `#${sessionId.slice(0, 8)}`
}

export function ResultsListPanel() {
  const { setActiveRun, activeRunId } = useShellStore()
  const { data: runs, isLoading, error } = useRunList()
  const completed = (runs ?? []).filter((run) => COMPLETED_STATUSES.has(String(run.status)))

  if (isLoading && !runs) {
    return <p className="empty-hint">보호 결과를 불러오는 중입니다…</p>
  }
  if (error) {
    return <p className="empty-hint">보호 결과를 불러오지 못했습니다.</p>
  }
  if (completed.length === 0) {
    return <p className="empty-hint">아직 종료된 보호 실행이 없습니다.</p>
  }

  return (
    <div className="run-list">
      {completed.map((run: RunSummary) => (
        <button
          key={run.session_id}
          type="button"
          className={`run-row${activeRunId === run.session_id ? ' is-active' : ''}`}
          onClick={() => setActiveRun(run.session_id)}
        >
          <div className="run-row-top">
            <span>{shortId(run.session_id)}</span>
            <span className={`badge is-${toneFor(run.bundle_status)}`}>Bundle {run.bundle_status ?? '확인 전'}</span>
            {Boolean(run.incident_count) && <span className="badge is-warn">사건 {run.incident_count}</span>}
          </div>
          <div className="run-row-path" title={run.workspace}>
            {run.workspace}
          </div>
        </button>
      ))}
    </div>
  )
}
