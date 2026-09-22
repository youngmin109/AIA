import { Icon } from '../common/Icon'
import { useShellStore } from '../../state/shellStore'
import { EventFeed } from '../sensors/EventFeed'
import { SensorHealthRow } from '../sensors/SensorHealthRow'
import { useRunStatus } from '../../hooks/useRunStatus'

export function RightPanel() {
  const { rightPanelCollapsed, toggleRightPanel, activeTabId } = useShellStore()
  // Owned once here rather than in EventFeed/SensorHealthRow separately --
  // both render from the same focused-tab run status, one 1s poll covers
  // both (see useRunStatus, gated to the focused tab only).
  const { data: status } = useRunStatus(activeTabId, { enabled: Boolean(activeTabId) })

  return (
    <aside className={`right-panel${rightPanelCollapsed ? ' is-collapsed' : ''}`} aria-hidden={rightPanelCollapsed}>
      <div className="right-panel-header">
        <span>실시간 기록</span>
        <button type="button" className="icon-button" title="패널 접기" onClick={toggleRightPanel}>
          <Icon name="close" size={14} />
        </button>
      </div>
      <div className="right-panel-content">
        {activeTabId && <SensorHealthRow sensorHealth={status?.sensor_health} evidenceSummary={status?.evidence_summary} />}
        <EventFeed runId={activeTabId} events={status?.events} evidenceChains={status?.evidence_chains} />
      </div>
    </aside>
  )
}
