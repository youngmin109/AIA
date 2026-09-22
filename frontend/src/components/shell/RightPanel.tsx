import { Icon } from '../common/Icon'
import { useShellStore } from '../../state/shellStore'
import { EventFeed } from '../sensors/EventFeed'

export function RightPanel() {
  const { rightPanelCollapsed, toggleRightPanel, activeTabId } = useShellStore()

  return (
    <aside className={`right-panel${rightPanelCollapsed ? ' is-collapsed' : ''}`} aria-hidden={rightPanelCollapsed}>
      <div className="right-panel-header">
        <span>실시간 기록</span>
        <button type="button" className="icon-button" title="패널 접기" onClick={toggleRightPanel}>
          <Icon name="close" size={14} />
        </button>
      </div>
      <div className="right-panel-content">
        <EventFeed runId={activeTabId} isFocused={Boolean(activeTabId)} />
      </div>
    </aside>
  )
}
