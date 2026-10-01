import { useState } from 'react'
import { Icon, type IconName } from '../common/Icon'
import { useShellStore, type ShellView } from '../../state/shellStore'
import guardianNormal from '../../assets/mascot/guardian-normal.png'
import guardianReview from '../../assets/mascot/guardian-review.png'
import guardianBlocked from '../../assets/mascot/guardian-blocked.png'
import guardianRecovery from '../../assets/mascot/guardian-recovery.png'
import { useRunStatus } from '../../hooks/useRunStatus'
import { isRunActive, useRunList } from '../../hooks/useRunList'

const NAV_ITEMS: Array<{ view: ShellView; icon: IconName; label: string }> = [
  { view: 'dashboard', icon: 'dashboard', label: '대시보드' },
  { view: 'terminal', icon: 'terminal', label: 'Agent CLI' },
  { view: 'policy', icon: 'settings', label: '정책 설정' },
  { view: 'audit', icon: 'history', label: '감사 기록' },
]

const TITLES: Record<ShellView, string> = {
  dashboard: '안전한 작업 현황',
  terminal: 'Agent CLI',
  policy: '정책 설정',
  audit: '감사 기록',
}

export function Sidebar() {
  const { activeView, sidebarCollapsed, setView, toggleSidebar, activeRunId, setActiveRun, openSettingsModal } = useShellStore()
  const [guideOpen, setGuideOpen] = useState(false)
  const [guideState, setGuideState] = useState<'normal' | 'review' | 'blocked' | 'recovery'>('normal')
  const { data: status } = useRunStatus(activeRunId, { enabled: Boolean(activeRunId) })
  const { data: runs } = useRunList({ hasActiveRun: Boolean(activeRunId) })
  const openRuns = (runs ?? []).filter(isRunActive).slice(0, 4)
  const guide = {
    normal: { image: guardianNormal, title: '정상 관찰', text: '실제 실행 요청과 Workspace 변화를 관찰해요.' },
    review: { image: guardianReview, title: '확인 필요', text: '정책상 추가 확인이 필요한 사건을 안내해요.' },
    blocked: { image: guardianBlocked, title: '위험 실행 차단', text: '정책 위반이 확인되면 실행·결과를 감사 기록으로 남겨요.' },
    recovery: { image: guardianRecovery, title: '복구와 검증', text: 'Checkpoint 기준 복구 후 무결성 검증 결과를 알려줘요.' },
  }[guideState]

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

  function openRun(sessionId: string) {
    setActiveRun(sessionId)
    setView('terminal')
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
      <section className="sidebar-sessions" aria-label="열린 보호 세션">
        <div className="sidebar-section-head">
          <span>열린 보호 세션</span>
          <button type="button" title="새 보호 실행" onClick={openSettingsModal}><Icon name="plus" size={14} /></button>
        </div>
        {openRuns.length > 0 ? openRuns.map((run) => (
          <button
            key={run.session_id}
            type="button"
            className={`sidebar-session${activeRunId === run.session_id ? ' is-active' : ''}`}
            onClick={() => openRun(run.session_id)}
            title={run.workspace ?? run.session_id}
          >
            <Icon name="terminal" size={14} />
            <span><b>Codex 세션 #{run.session_id.slice(0, 8)}</b><small>{run.workspace ?? 'Workspace 확인 중'}</small></span>
          </button>
        )) : <p className="sidebar-session-empty">실행을 시작하면 여기에서 세션을 다시 열 수 있어요.</p>}
      </section>
      <button type="button" className="sidebar-guardian" onClick={() => setGuideOpen(true)} title="아이아 가디언 도움말">
        <img src={guardianNormal} alt="" />
        <span>가디언 사용 안내</span>
      </button>
      <section className="sidebar-workspace" aria-label="현재 보호 실행">
        <span>현재 보호 실행</span>
        <b title={status?.session?.workspace ?? undefined}>{status?.session?.workspace ?? '선택된 Workspace 없음'}</b>
        <small>{activeRunId ? `세션 #${activeRunId.slice(0, 8)} · ${status?.session?.status ?? '연결 중'}` : '보호 실행 시작 전'}</small>
      </section>
      {guideOpen && (
        <div className="guardian-guide-popover" role="dialog" aria-label="아이아 가디언 도움말">
          <button type="button" className="icon-button guardian-guide-close" onClick={() => setGuideOpen(false)} aria-label="도움말 닫기"><Icon name="close" size={14} /></button>
          <img src={guide.image} alt={`아이아 가디언 ${guide.title}`} />
          <strong>아이아 가디언이 사용을 도와드려요.</strong>
          <p><b>{guide.title}</b> · {guide.text} 가디언은 Agent가 아니라, Codex의 실제 실행과 AIA의 보호 상태를 설명하는 안내자입니다.</p>
          <ol className="guardian-guide-flow">
            <li>보호 실행을 만들고 Workspace와 정책을 선택합니다.</li>
            <li>Agent CLI에 작업을 입력합니다.</li>
            <li>위험하거나 범위 밖인 요청은 안내를 확인합니다.</li>
            <li>결과와 감사 기록은 실행이 끝난 뒤 확인합니다.</li>
          </ol>
          <div className="guardian-guide-states" aria-label="가디언 상태 미리보기">
            {(['normal', 'review', 'blocked', 'recovery'] as const).map((state) => <button key={state} type="button" className={guideState === state ? 'is-active' : ''} onClick={() => setGuideState(state)}>{({ normal: '정상', review: '확인', blocked: '차단', recovery: '복구' })[state]}</button>)}
          </div>
        </div>
      )}
    </aside>
  )
}

export { TITLES as SIDEBAR_VIEW_TITLES }
