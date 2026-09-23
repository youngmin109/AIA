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

  return (
    <aside className={`right-panel${rightPanelCollapsed ? ' is-collapsed' : ''}`} aria-hidden={rightPanelCollapsed}>
      <div className="right-panel-header">
        <span>실시간 활동</span>
        <button type="button" className="icon-button" title="패널 접기" onClick={toggleRightPanel}>
          <Icon name="close" size={14} />
        </button>
      </div>
      <div className="right-panel-content">
        <p className="right-panel-subtitle">Hook · Process · File Evidence</p>
        {activeRunId && <SensorHealthRow sensorHealth={status?.sensor_health} evidenceSummary={status?.evidence_summary} />}
        <EventFeed runId={activeRunId} events={status?.events} evidenceChains={status?.evidence_chains} />
      </div>
    </aside>
  )
}
