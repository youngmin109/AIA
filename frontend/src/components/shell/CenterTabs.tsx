import { Icon } from '../common/Icon'
import { useShellStore } from '../../state/shellStore'

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
        {activeTab ? (
          <TerminalPanePlaceholder tabId={activeTab.id} title={activeTab.title} />
        ) : (
          <div className="center-empty-state">
            <strong>열린 실행이 없습니다</strong>
            <p>좌측 지난 실행 목록에서 항목을 선택하거나, + 버튼으로 새 보호 실행을 시작하세요.</p>
          </div>
        )}
      </div>
    </div>
  )
}

function TerminalPanePlaceholder({ tabId, title }: { tabId: string; title: string }) {
  // Milestone 3 placeholder. Replaced by the real TerminalPane (ported
  // VT100 emulator + WinPTY WebSocket client) in milestone 4.
  return (
    <div className="center-empty-state">
      <strong>{title}</strong>
      <p>
        Codex 터미널 자리 (session {tabId}) — 실제 WebSocket 연결은 마일스톤 4에서 이식됩니다.
      </p>
    </div>
  )
}
