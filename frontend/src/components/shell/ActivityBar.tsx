import { Icon, type IconName } from '../common/Icon'
import { useShellStore, type ShellView } from '../../state/shellStore'
import { BrandCorner } from './BrandCorner'
import { ThemeToggle } from '../common/ThemeToggle'

const NAV_ITEMS: Array<{ view: ShellView; icon: IconName; label: string }> = [
  { view: 'dashboard', icon: 'dashboard', label: '대시보드' },
  { view: 'history', icon: 'history', label: '지난 실행' },
  { view: 'results', icon: 'results', label: '보호 결과' },
]

export function ActivityBar() {
  const { activeView, sidebarCollapsed, setView, toggleSidebar, openSettingsModal } = useShellStore()

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
    <div className="activity-bar">
      <BrandCorner />
      <nav className="activity-bar-nav" aria-label="AIA 주요 메뉴">
        {NAV_ITEMS.map((item) => (
          <button
            key={item.view}
            type="button"
            className={`activity-bar-btn${activeView === item.view && !sidebarCollapsed ? ' is-active' : ''}`}
            title={item.label}
            aria-label={item.label}
            aria-current={activeView === item.view && !sidebarCollapsed ? 'true' : undefined}
            onClick={() => handleNavClick(item.view)}
          >
            <Icon name={item.icon} />
          </button>
        ))}
        <button
          type="button"
          className="activity-bar-btn"
          title="보호 세팅"
          aria-label="보호 세팅"
          onClick={openSettingsModal}
        >
          <Icon name="settings" />
        </button>
      </nav>
      <div className="activity-bar-spacer" />
      <div className="activity-bar-bottom">
        <ThemeToggle />
      </div>
    </div>
  )
}
