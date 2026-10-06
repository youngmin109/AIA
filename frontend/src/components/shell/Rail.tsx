import { useState } from 'react'
import { Icon, type IconName } from '../common/Icon'
import { GuardianAvatar } from '../common/GuardianAvatar'
import { useGuardianState } from '../../hooks/useGuardianState'
import { useRunStatus } from '../../hooks/useRunStatus'
import { isRunActive, useRunList } from '../../hooks/useRunList'
import { useShellStore, type ShellView } from '../../state/shellStore'
import { GuardianGuide, type GuideTopic } from './GuardianGuide'

const RAIL_ITEMS: Array<{ view: ShellView; icon: IconName; label: string }> = [
  { view: 'home', icon: 'home', label: '홈' },
  { view: 'work', icon: 'chat', label: '작업창' },
  { view: 'policy', icon: 'shieldPlain', label: '정책' },
  { view: 'history', icon: 'records', label: '기록' },
  { view: 'settings', icon: 'settings', label: '설정' },
]

/** Glass navigation rail: five destinations and the guardian help. */
export function Rail() {
  const { activeView, setView, activeRunId } = useShellStore()
  const { data: runs } = useRunList()
  const { data: status } = useRunStatus(activeRunId, { enabled: Boolean(activeRunId) })
  const guardian = useGuardianState()
  const [guideTopic, setGuideTopic] = useState<GuideTopic | null>(null)
  const liveRuns = (runs ?? []).filter(isRunActive).length

  function openGuide() {
    const ended = ['COMPLETED', 'ABORTED'].includes(status?.session?.status ?? '')
    setGuideTopic(!activeRunId ? 'start' : guardian.state === 'blocked' || guardian.label === '사용자 확인' ? 'safety' : ended ? 'recovery' : 'start')
  }

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
      <div className="rail-spacer" />
      <button type="button" className="rail-guardian" onClick={openGuide} title="아이아 가디언 도움말" aria-label="아이아 가디언 도움말" aria-expanded={guideTopic !== null}>
        <GuardianAvatar state={guardian.state} alt="" size="sidebar" />
      </button>
      {guideTopic && <GuardianGuide guardian={guardian} initialTopic={guideTopic} onClose={() => setGuideTopic(null)} />}
    </nav>
  )
}
