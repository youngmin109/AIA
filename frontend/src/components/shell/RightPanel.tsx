import { isSessionRunning } from '../../api/display'
import { Icon } from '../common/Icon'
import { useShellStore } from '../../state/shellStore'
import { EventFeed } from '../sensors/EventFeed'
import { SensorHealthRow } from '../sensors/SensorHealthRow'
import { useRunStatus } from '../../hooks/useRunStatus'
import { sessionDisplayName } from './sessionLabel'

export function RightPanel() {
  const { rightPanelCollapsed, toggleRightPanel, activeRunId } = useShellStore()
  // Owned once here rather than in EventFeed/SensorHealthRow separately --
  // both render from the same active-run status, one 1s poll covers both
  // (see useRunStatus, gated to whether a run is active).
  const { data: status, error, updatedAt } = useRunStatus(activeRunId, { enabled: Boolean(activeRunId) })
  const live = isSessionRunning(status?.session?.status, status?.runtime_reconciliation?.orphaned)
  // Without a selected run the panel would only say "nothing to show", so it
  // gives its width back to the main view until a run is selected.
  const collapsed = rightPanelCollapsed || !activeRunId

  return (
    <aside className={`right-panel${collapsed ? ' is-collapsed' : ''}`} aria-hidden={collapsed}>
      <div className="right-panel-header">
        <span>{live ? '실시간 활동' : '세션 활동 기록'}</span>
        <button type="button" className="icon-button" title="패널 접기" onClick={toggleRightPanel}>
          <Icon name="close" size={14} />
        </button>
      </div>
      <div className="right-panel-content">
        <p className="right-panel-subtitle">실행 요청 · 프로세스 · 파일 관찰</p>
        <div className="activity-session-summary">
          <span>{activeRunId ? sessionDisplayName(status?.session?.workspace) : '현재 세션 없음'}</span>
          <span>{activeRunId ? `${status?.evidence_summary?.filesystem_events ?? '—'}건의 변경 이벤트` : '실행 대기'}</span>
        </div>
        {error && <p role="alert" className="validation-note">연결 확인 필요 · 최신 상태를 가져오지 못했습니다.</p>}
        {updatedAt && <small>마지막 확인 {new Date(updatedAt).toLocaleTimeString('ko-KR')}{!live ? ' · 종료된 세션의 기록' : ''}</small>}
        {activeRunId && <SensorHealthRow sensorHealth={status?.sensor_health} evidenceSummary={status?.evidence_summary} />}
        <EventFeed runId={activeRunId} events={status?.events} evidenceChains={status?.evidence_chains} />
      </div>
      <footer className="right-panel-guide"><b>아이아 가디언의 관찰 기준</b><span>에이전트의 요청만 신뢰하지 않고 실제 프로세스와 파일 변화를 함께 확인합니다.</span></footer>
    </aside>
  )
}
