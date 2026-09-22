import { useShellStore } from '../../state/shellStore'
import { DashboardPanel } from '../dashboard/DashboardPanel'
import { RunListPanel } from '../history/RunListPanel'
import { ResultsListPanel } from '../results/ResultsListPanel'

const TITLES: Record<string, string> = {
  dashboard: '대시보드',
  history: '지난 실행',
  results: '보호 결과',
}

export function Sidebar() {
  const { activeView, sidebarCollapsed } = useShellStore()

  return (
    <aside className={`sidebar${sidebarCollapsed ? ' is-collapsed' : ''}`} aria-hidden={sidebarCollapsed}>
      <div className="sidebar-header">{TITLES[activeView]}</div>
      <div className="sidebar-content">
        {activeView === 'dashboard' && <DashboardPanel />}
        {activeView === 'history' && <RunListPanel />}
        {activeView === 'results' && <ResultsListPanel />}
      </div>
    </aside>
  )
}
