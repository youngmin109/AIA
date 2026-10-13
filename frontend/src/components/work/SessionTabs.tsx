import { Icon } from '../common/Icon'
import { useShellStore } from '../../state/shellStore'
import { useRunList } from '../../hooks/useRunList'
import { useSessionAttention } from '../../hooks/useSessionAttention'
import { MAX_SESSIONS, sessionTabs } from '../../api/sessionTabs'

/** Conversation tabs above the work view: one per live run, each in its own folder, plus "새 대화". */
export function SessionTabs() {
  const { activeRunId, setActiveRun, openNewRun } = useShellStore()
  const { data: runs } = useRunList()
  const tabs = sessionTabs(runs ?? [], activeRunId)
  const live = tabs.filter(tab => tab.state !== 'ended')
  const attention = useSessionAttention(live.filter(tab => tab.id !== activeRunId).map(tab => tab.id))
  const full = live.length >= MAX_SESSIONS
  if (tabs.length === 0) return null
  return (
    <div className="session-tabs" role="tablist" aria-label="대화방">
      {tabs.map(tab => {
        const waiting = attention.has(tab.id)
        return (
          <button
            key={tab.id} type="button" role="tab" aria-selected={tab.id === activeRunId} title={tab.path}
            className={`session-tab is-${tab.state}${waiting ? ' is-attention' : ''}`}
            onClick={() => setActiveRun(tab.id)}
          >
            <span className="session-tab-dot" aria-hidden="true" />
            <span className="session-tab-name">{tab.name}</span>
            {waiting ? <span className="session-tab-badge">확인 필요</span>
              : tab.state === 'ended' ? <small>끝남</small>
              : tab.state === 'preparing' ? <small>준비 중</small> : null}
          </button>
        )
      })}
      <button
        type="button" className="session-tab-new" onClick={openNewRun} disabled={full}
        title={full ? `동시에 열 수 있는 대화는 최대 ${MAX_SESSIONS}개예요` : '다른 작업 폴더에서 새 대화를 시작해요'}
      >
        <Icon name="plus" size={14} />새 대화
      </button>
    </div>
  )
}
