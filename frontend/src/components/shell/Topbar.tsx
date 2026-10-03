import { Button } from '../common/Button'
import { useShellStore } from '../../state/shellStore'
import { ThemeToggle } from '../common/ThemeToggle'
import { SIDEBAR_VIEW_TITLES } from './Sidebar'
import { displayStatus } from '../../api/display'
import { Icon } from '../common/Icon'
import { usePreflight } from '../../hooks/usePreflight'

export function Topbar() {
  const { activeView, rightPanelCollapsed, toggleRightPanel, activeRunId, toggleSidebar, sidebarCollapsed } = useShellStore()
  const { data: preflight } = usePreflight()
  const ready = preflight?.readiness_code === 'READY'
  // The activity panel only has content for a selected run (see RightPanel).
  const panelShown = !rightPanelCollapsed && Boolean(activeRunId)

  return (
    <header className="topbar">
      <div className="topbar-titles"><Button variant="icon" onClick={toggleSidebar} aria-expanded={!sidebarCollapsed} aria-label={sidebarCollapsed ? '메뉴 열기' : '메뉴 접기'}><Icon name="collapseLeft" /></Button>
        <h1 className="topbar-title">{SIDEBAR_VIEW_TITLES[activeView]}</h1>
      </div>
      <div className="topbar-actions">
        <ThemeToggle />
        <button
          type="button"
          className="topbar-activity-button"
          onClick={toggleRightPanel}
          disabled={!activeRunId}
          title={activeRunId ? undefined : '실행을 선택하면 실시간 활동을 볼 수 있습니다'}
        >
          <Icon name="results" size={14} />
          {panelShown ? '활동 숨기기' : '활동 보기'}
        </button>
        <span className={`readiness-badge${ready ? ' is-ready' : ''}`}>{displayStatus(preflight?.readiness_code ?? 'CHECKING')}</span>
      </div>
    </header>
  )
}
