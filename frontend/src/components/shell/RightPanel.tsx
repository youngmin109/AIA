import { Icon } from '../common/Icon'
import { useShellStore } from '../../state/shellStore'
import { EventFeed } from '../sensors/EventFeed'
import { SensorHealthRow } from '../sensors/SensorHealthRow'
import { useRunStatus } from '../../hooks/useRunStatus'

export function RightPanel() {
  const { rightPanelCollapsed, toggleRightPanel, activeRunId } = useShellStore()
  // Owned once here rather than in EventFeed/SensorHealthRow separately --
  // both render from the same active-run status, one 1s poll covers both
  // (see useRunStatus, gated to whether a run is active).
  const { data: status } = useRunStatus(activeRunId, { enabled: Boolean(activeRunId) })
  // Without a selected run the panel would only say "nothing to show", so it
  // gives its width back to the main view until a run is selected.
  const collapsed = rightPanelCollapsed || !activeRunId

  return (
    <aside className={`right-panel${collapsed ? ' is-collapsed' : ''}`} aria-hidden={collapsed}>
      <div className="right-panel-header">
        <span>실시간 활동</span>
        <button type="button" className="icon-button" title="패널 접기" onClick={toggleRightPanel}>
          <Icon name="close" size={14} />
        </button>
      </div>
      <div className="right-panel-content">
        <p className="right-panel-subtitle">Hook · Process · File Evidence</p>
        <div className="activity-session-summary">
          <span>{activeRunId ? `현재 세션 #${activeRunId.slice(0, 8)}` : '현재 세션 없음'}</span>
          <span>{activeRunId ? `${status?.evidence_summary?.filesystem_events ?? 0} 파일 변경` : '실행 대기'}</span>
        </div>
        {activeRunId && <SensorHealthRow sensorHealth={status?.sensor_health} evidenceSummary={status?.evidence_summary} />}
        <EventFeed runId={activeRunId} events={status?.events} evidenceChains={status?.evidence_chains} />
      </div>
      <footer className="right-panel-guide"><b>아이아 가디언의 관찰 기준</b><span>Agent의 요청만 신뢰하지 않고 실제 프로세스와 파일 변화를 함께 확인합니다.</span></footer>
    </aside>
  )
}
