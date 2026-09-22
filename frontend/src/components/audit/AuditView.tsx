import { useShellStore } from '../../state/shellStore'
import { useRunList } from '../../hooks/useRunList'
import { ResultView } from '../results/ResultView'
import type { RunSummary } from '../../api/types'

const ENDED_STATUSES = new Set(['COMPLETED', 'ABORTED', 'FAILED'])

function shortId(sessionId: string): string {
  return `#${sessionId.slice(0, 8)}`
}

function toneFor(status: string | undefined): 'ok' | 'warn' | 'bad' {
  const upper = String(status || '').toUpperCase()
  if (['COMPLETED', 'RUNNING'].includes(upper)) return 'ok'
  if (['FAILED', 'ABORTED'].includes(upper)) return 'bad'
  return 'warn'
}

// Absorbs the old RunListPanel/ResultsListPanel's list+select behavior into
// one view: every run (running included) browsable from a single list,
// with the selected run's verdict/evidence shown alongside it.
export function AuditView() {
  const { activeRunId, setActiveRun, setView } = useShellStore()
  const { data: runs, isLoading, error } = useRunList({ hasActiveRun: true })
  const selected = runs?.find((run) => run.session_id === activeRunId) ?? null
  const selectedEnded = Boolean(selected && ENDED_STATUSES.has(String(selected.status)))

  return (
    <div className="dashboard-view">
      <div className="audit-grid">
        <div className="card audit-list-card">
          <div className="dashboard-card-title audit-list-title">전체 실행 기록</div>
          <div className="audit-list-scroll">
            {isLoading && !runs && <p className="empty-hint">불러오는 중입니다…</p>}
            {error && <p className="empty-hint">실행 기록을 불러오지 못했습니다.</p>}
            {runs && runs.length === 0 && <p className="empty-hint">아직 보호 실행 기록이 없습니다.</p>}
            <div className="run-list">
              {(runs ?? []).map((run: RunSummary) => (
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
          </div>
        </div>

        <div className="card audit-detail-card">
          {!selected && (
            <div className="center-empty-state">
              <strong>왼쪽에서 실행을 선택하세요</strong>
              <p>실행 기록을 선택하면 판정과 증거 요약을 확인할 수 있습니다.</p>
            </div>
          )}
          {selected && !selectedEnded && (
            <div className="center-empty-state">
              <strong>이 실행은 아직 진행 중입니다</strong>
              <p>실시간 상태와 명령 입력은 Agent CLI에서 확인할 수 있습니다.</p>
              <button type="button" className="cta-button" style={{ width: 'auto', padding: '8px 16px' }} onClick={() => setView('terminal')}>
                Agent CLI 열기 →
              </button>
            </div>
          )}
          {selected && selectedEnded && activeRunId && <ResultView runId={activeRunId} showEvidenceLog />}
        </div>
      </div>
    </div>
  )
}
