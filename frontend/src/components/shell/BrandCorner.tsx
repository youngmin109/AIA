import { Icon } from '../common/Icon'
import { useShellStore } from '../../state/shellStore'

export function BrandCorner() {
  const { sidebarCollapsed, toggleSidebar } = useShellStore()

  return (
    <button
      type="button"
      className="brand-corner"
      onClick={toggleSidebar}
      title={sidebarCollapsed ? 'AIA · 사이드바 펼치기' : 'AIA · 사이드바 접기'}
      aria-pressed={!sidebarCollapsed}
    >
      <Icon name="brand" size={20} />
    </button>
  )
}
