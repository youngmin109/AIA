import { useShellStore } from '../../state/shellStore'
import { useRunList } from '../../hooks/useRunList'
import type { RunSummary } from '../../api/types'

function toneFor(status: string | undefined): 'ok' | 'warn' | 'bad' {
  const upper = String(status || '').toUpperCase()
  if (['COMPLETED', 'RUNNING'].includes(upper)) return 'ok'
  if (['FAILED', 'ABORTED'].includes(upper)) return 'bad'
  return 'warn'
}

function shortId(sessionId: string): string {
  return `#${sessionId.slice(0, 8)}`
}

export function RunListPanel() {
  const { setActiveRun, activeRunId } = useShellStore()
  const { data: runs, isLoading, error } = useRunList()

  if (isLoading && !runs) {
    return <p className="empty-hint">실행 기록을 불러오는 중입니다…</p>
  }
  if (error) {
    return <p className="empty-hint">실행 기록을 불러오지 못했습니다.</p>
  }
  if (!runs || runs.length === 0) {
    return <p className="empty-hint">아직 보호 실행 기록이 없습니다.</p>
  }

  return (
    <div className="run-list">
      {runs.map((run: RunSummary) => (
        <button
          key={run.session_id}
          type="button"
          className={`run-row${activeRunId === run.session_id ? ' is-active' : ''}`}
          onClick={() => setActiveRun(run.session_id)}
        >
          <div className="run-row-top">
            <span>{shortId(run.session_id)}</span>
            <span className={`badge is-${toneFor(run.status)}`}>{run.status ?? '상태 미확인'}</span>
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
