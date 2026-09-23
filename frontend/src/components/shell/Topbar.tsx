import { useShellStore } from '../../state/shellStore'
import { ThemeToggle } from '../common/ThemeToggle'
import { SIDEBAR_VIEW_TITLES } from './Sidebar'
import { Icon } from '../common/Icon'
import { usePreflight } from '../../hooks/usePreflight'

export function Topbar() {
  const { activeView, rightPanelCollapsed, toggleRightPanel } = useShellStore()
  const { data: preflight } = usePreflight()
  const ready = preflight?.readiness_code === 'READY'

  return (
    <header className="topbar">
      <div className="topbar-titles">
        <span className="topbar-overline">AIA GUARDIAN</span>
        <h1 className="topbar-title">{SIDEBAR_VIEW_TITLES[activeView]}</h1>
      </div>
      <div className="topbar-actions">
        <ThemeToggle />
        <button type="button" className="topbar-activity-button" onClick={toggleRightPanel}>
          <Icon name="results" size={14} />
          {rightPanelCollapsed ? '활동 보기' : '활동 숨기기'}
        </button>
        <span className={`readiness-badge${ready ? ' is-ready' : ''}`}>{preflight?.readiness_code ?? 'CHECKING'}</span>
      </div>
    </header>
  )
}
