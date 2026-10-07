import { Icon, type IconName } from '../common/Icon'
import { isRunActive, useRunList } from '../../hooks/useRunList'
import { useShellStore, type ShellView } from '../../state/shellStore'

const RAIL_ITEMS: Array<{ view: ShellView; icon: IconName; label: string }> = [
  { view: 'home', icon: 'home', label: '홈' },
  { view: 'work', icon: 'chat', label: '작업창' },
  { view: 'policy', icon: 'shieldPlain', label: '정책' },
  { view: 'history', icon: 'records', label: '기록' },
  { view: 'settings', icon: 'settings', label: '설정' },
]

/** Glass navigation rail: five destinations. The guardian floats on its own (GuardianPet). */
export function Rail() {
  const { activeView, setView } = useShellStore()
  const { data: runs } = useRunList()
  const liveRuns = (runs ?? []).filter(isRunActive).length

  return (
    <nav className="rail" aria-label="주 메뉴">
      <div className="rail-logo" aria-hidden="true">AIA</div>
      <div className="rail-nav">
        {RAIL_ITEMS.map(item => (
          <button
            key={item.view}
            type="button"
            className="rail-item"
            aria-current={activeView === item.view ? 'page' : undefined}
            onClick={() => setView(item.view)}
          >
            <Icon name={item.icon} size={22} />
            {item.label}
            {item.view === 'work' && liveRuns > 0 && <span className="rail-live-dot" title="실행 중" />}
          </button>
        ))}
      </div>
    </nav>
  )
}
