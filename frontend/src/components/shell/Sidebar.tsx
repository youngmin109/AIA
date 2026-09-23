import { useState } from 'react'
import { Icon, type IconName } from '../common/Icon'
import { useShellStore, type ShellView } from '../../state/shellStore'
import guardianNormal from '../../assets/mascot/guardian-normal.png'

const NAV_ITEMS: Array<{ view: ShellView; icon: IconName; label: string }> = [
  { view: 'dashboard', icon: 'dashboard', label: '대시보드' },
  { view: 'terminal', icon: 'terminal', label: 'Agent CLI' },
  { view: 'policy', icon: 'settings', label: '정책 설정' },
  { view: 'audit', icon: 'history', label: '감사 기록' },
]

const TITLES: Record<ShellView, string> = {
  dashboard: '대시보드',
  terminal: 'Agent CLI',
  policy: '정책 설정',
  audit: '감사 기록',
}

export function Sidebar() {
  const { activeView, sidebarCollapsed, setView, toggleSidebar } = useShellStore()
  const [guideOpen, setGuideOpen] = useState(false)

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
          AIA Guardian
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
      <button type="button" className="sidebar-guardian" onClick={() => setGuideOpen(true)} title="아이아 가디언 도움말">
        <img src={guardianNormal} alt="아이아 가디언" />
        <span><b>아이아 가디언</b><small>실제 실행을 관찰하고<br />안전한 상태를 안내해요.</small></span>
      </button>
      {guideOpen && (
        <div className="guardian-guide-popover" role="dialog" aria-label="아이아 가디언 도움말">
          <button type="button" className="icon-button guardian-guide-close" onClick={() => setGuideOpen(false)} aria-label="도움말 닫기"><Icon name="close" size={14} /></button>
          <img src={guardianNormal} alt="아이아 가디언" />
          <strong>아이아 가디언은 Agent가 아닙니다.</strong>
          <p>Codex의 요청만 믿지 않고 Hook·Process·File Sensor가 확인한 실제 실행 사실을 이해하기 쉽게 안내합니다.</p>
        </div>
      )}
    </aside>
  )
}

export { TITLES as SIDEBAR_VIEW_TITLES }
