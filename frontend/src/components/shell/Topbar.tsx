import { useShellStore } from '../../state/shellStore'
import { ThemeToggle } from '../common/ThemeToggle'
import { SIDEBAR_VIEW_TITLES } from './Sidebar'

export function Topbar() {
  const { activeView } = useShellStore()

  return (
    <header className="topbar">
      <div className="topbar-titles">
        <span className="topbar-overline">AIA GUARDIAN</span>
        <h1 className="topbar-title">{SIDEBAR_VIEW_TITLES[activeView]}</h1>
      </div>
      <div className="topbar-actions">
        <ThemeToggle />
      </div>
    </header>
  )
}
