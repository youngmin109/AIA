import { displayStatus, statusTone } from '../../api/display'
import { useShellStore } from '../../state/shellStore'
import { useRunList } from '../../hooks/useRunList'
import { ResultView } from '../results/ResultView'
import type { RunSummary } from '../../api/types'
import { sessionCreatedLabel, sessionDisplayName, sessionShortId } from '../shell/sessionLabel'

const ENDED_STATUSES = new Set(['COMPLETED', 'ABORTED', 'FAILED'])


// Absorbs the old RunListPanel/ResultsListPanel's list+select behavior into
// one view: every run (running included) browsable from a single list,
// with the selected run's verdict/evidence shown alongside it.
export function AuditView() {
  const { activeRunId, setActiveRun, setView } = useShellStore()
  const { data: runs, isLoading, error } = useRunList()
  const selected = runs?.find((run) => run.session_id === activeRunId) ?? null
  const selectedEnded = Boolean(selected && ENDED_STATUSES.has(String(selected.status)))
  const selectedOrphaned = Boolean((selected?.runtime_reconciliation as { orphaned?: boolean } | undefined)?.orphaned)

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
                    <span>{sessionDisplayName(run.workspace)}</span>
                    <span className={`badge is-${statusTone(run.status)}`}>{displayStatus(run.status)}</span>
                    {Boolean(run.incident_count) && <span className="badge is-warn">사건 {run.incident_count}</span>}
                  </div>
                  <div className="run-row-path" title={run.workspace}>
                    {run.workspace ?? '작업공간 확인 중'}
                  </div>
                  <div className="run-row-meta"><span>시작 {sessionCreatedLabel(run.created_at)}</span><code>{sessionShortId(run.session_id)}</code></div>
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
          {selected && !selectedEnded && selectedOrphaned && (
            <div className="center-empty-state"><strong>이전 실행의 연결이 끊겼습니다</strong><p>저장된 상태는 실행 중으로 남아 있지만, 현재 AIA가 대화를 다시 연결할 수 없습니다. 새 보호 실행 설정에서 작업공간을 선택해 안전한 정리 가능 여부를 확인하세요. 살아 있는 프로세스는 자동으로 강제 종료하지 않습니다.</p></div>
          )}
          {selected && !selectedEnded && !selectedOrphaned && (
            <div className="center-empty-state">
              <strong>이 실행은 아직 진행 중입니다</strong>
              <p>실시간 상태와 명령 입력은 에이전트 작업에서 확인할 수 있습니다.</p>
              <button type="button" className="cta-button" style={{ width: 'auto', padding: '8px 16px' }} onClick={() => setView('terminal')}>
                에이전트 작업 열기 →
              </button>
            </div>
          )}
          {selected && selectedEnded && activeRunId && <ResultView runId={activeRunId} showEvidenceLog />}
        </div>
      </div>
    </div>
  )
}
