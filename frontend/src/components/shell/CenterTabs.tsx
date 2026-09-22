import { Icon } from '../common/Icon'
import { useShellStore } from '../../state/shellStore'
import { TerminalPane } from '../terminal/TerminalPane'

export function CenterTabs() {
  const { openTabs, activeTabId, setActiveTab, closeTab, openSettingsModal, rightPanelCollapsed, toggleRightPanel } =
    useShellStore()

  const activeTab = openTabs.find((tab) => tab.id === activeTabId)

  return (
    <div className="center-pane">
      <div className="tab-strip">
        {openTabs.map((tab) => (
          <button
            key={tab.id}
            type="button"
            className={`tab-item${tab.id === activeTabId ? ' is-active' : ''}`}
            onClick={() => setActiveTab(tab.id)}
          >
            <span>{tab.title}</span>
            <span
              role="button"
              tabIndex={-1}
              className="tab-item-close"
              onClick={(event) => {
                event.stopPropagation()
                closeTab(tab.id)
              }}
              title="탭 닫기"
            >
              <Icon name="close" size={12} />
            </span>
          </button>
        ))}
        <button type="button" className="tab-strip-action" title="새 보호 실행" onClick={openSettingsModal}>
          <Icon name="plus" size={16} />
        </button>
        <div className="tab-strip-spacer" />
        <button
          type="button"
          className={`tab-strip-action${rightPanelCollapsed ? '' : ' is-active'}`}
          title={rightPanelCollapsed ? '실시간 기록 패널 펼치기' : '실시간 기록 패널 접기'}
          aria-pressed={!rightPanelCollapsed}
          onClick={toggleRightPanel}
        >
          <Icon name="results" size={16} />
        </button>
      </div>
      <div className="center-content">
        {/* Every open tab stays mounted (display:none when inactive) so its
            terminal WebSocket keeps running in the background instead of
            reconnecting on every tab switch -- only the 1s run-status poll
            is gated to the focused tab (see TerminalPane/useRunStatus). */}
        {openTabs.map((tab) => (
          <div key={tab.id} style={{ display: tab.id === activeTabId ? 'flex' : 'none', height: '100%' }}>
            <TerminalPane runId={tab.id} isFocused={tab.id === activeTabId} />
          </div>
        ))}
        {!activeTab && (
          <div className="center-empty-state">
            <strong>열린 실행이 없습니다</strong>
            <p>좌측 지난 실행 목록에서 항목을 선택하거나, + 버튼으로 새 보호 실행을 시작하세요.</p>
          </div>
        )}
      </div>
    </div>
  )
}
