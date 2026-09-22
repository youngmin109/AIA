import { Icon, type IconName } from '../common/Icon'
import { useShellStore, type ShellView } from '../../state/shellStore'
import { DashboardPanel } from '../dashboard/DashboardPanel'
import { RunListPanel } from '../history/RunListPanel'
import { ResultsListPanel } from '../results/ResultsListPanel'

const NAV_ITEMS: Array<{ view: ShellView; icon: IconName; label: string }> = [
  { view: 'dashboard', icon: 'dashboard', label: '대시보드' },
  { view: 'history', icon: 'history', label: '지난 실행' },
  { view: 'results', icon: 'results', label: '보호 결과' },
]

const TITLES: Record<ShellView, string> = {
  dashboard: '대시보드',
  history: '지난 실행',
  results: '보호 결과',
}

export function Sidebar() {
  const { activeView, sidebarCollapsed, setView, toggleSidebar } = useShellStore()

  function handleNavClick(view: ShellView) {
    if (!sidebarCollapsed && activeView === view) {
      toggleSidebar()
      return
    }
    setView(view)
    if (sidebarCollapsed) {
      toggleSidebar()
    }
  }

  return (
    <aside className={`app-sidebar${sidebarCollapsed ? ' is-collapsed' : ''}`}>
      <div className="app-sidebar-brand">
        <span className="app-sidebar-brandmark">
          <Icon name="brand" size={18} />
        </span>
        <span className="app-sidebar-brand-name">
          AIA
          <small>PROTECTED RUN</small>
        </span>
        <button
          type="button"
          className="app-sidebar-collapse"
          onClick={toggleSidebar}
          title="사이드바 접기"
          aria-pressed={!sidebarCollapsed}
        >
          <Icon name="collapseLeft" size={14} />
        </button>
      </div>

      <nav className="app-sidebar-nav" aria-label="AIA 주요 메뉴">
        {NAV_ITEMS.map((item) => (
          <button
            key={item.view}
            type="button"
            className={`app-sidebar-nav-btn${activeView === item.view && !sidebarCollapsed ? ' is-active' : ''}`}
            title={item.label}
            aria-current={activeView === item.view && !sidebarCollapsed ? 'true' : undefined}
            onClick={() => handleNavClick(item.view)}
          >
            <span className="app-sidebar-nav-btn-icon">
              <Icon name={item.icon} size={17} />
            </span>
            <span className="app-sidebar-nav-btn-label">{item.label}</span>
          </button>
        ))}
      </nav>

      <div className="app-sidebar-section" aria-hidden={sidebarCollapsed}>
        <div className="app-sidebar-section-label">{TITLES[activeView]}</div>
        <div className="app-sidebar-section-content">
          {activeView === 'dashboard' && <DashboardPanel />}
          {activeView === 'history' && <RunListPanel />}
          {activeView === 'results' && <ResultsListPanel />}
        </div>
      </div>
    </aside>
  )
}

export { TITLES as SIDEBAR_VIEW_TITLES }
