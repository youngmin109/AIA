import { useState } from 'react'
import { Icon, type IconName } from '../common/Icon'
import { useShellStore, type ShellView } from '../../state/shellStore'
import guardianNormal from '../../assets/mascot/guardian-normal.png'
import guardianReview from '../../assets/mascot/guardian-review.png'
import guardianBlocked from '../../assets/mascot/guardian-blocked.png'
import guardianRecovery from '../../assets/mascot/guardian-recovery.png'
import { useRunStatus } from '../../hooks/useRunStatus'

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
  const { activeView, sidebarCollapsed, setView, toggleSidebar, activeRunId } = useShellStore()
  const [guideOpen, setGuideOpen] = useState(false)
  const [guideState, setGuideState] = useState<'normal' | 'review' | 'blocked' | 'recovery'>('normal')
  const { data: status } = useRunStatus(activeRunId, { enabled: Boolean(activeRunId) })
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
      <section className="sidebar-workspace" aria-label="현재 보호 실행">
        <span>현재 보호 실행</span>
        <b title={status?.session?.workspace ?? undefined}>{status?.session?.workspace ?? '선택된 Workspace 없음'}</b>
        <small>{activeRunId ? `세션 #${activeRunId.slice(0, 8)} · ${status?.session?.status ?? '연결 중'}` : '보호 실행 시작 전'}</small>
      </section>
      {guideOpen && (
        <div className="guardian-guide-popover" role="dialog" aria-label="아이아 가디언 도움말">
          <button type="button" className="icon-button guardian-guide-close" onClick={() => setGuideOpen(false)} aria-label="도움말 닫기"><Icon name="close" size={14} /></button>
          <img src={guide.image} alt={`아이아 가디언 ${guide.title}`} />
          <strong>아이아 가디언은 Agent가 아닙니다.</strong>
          <p><b>{guide.title}</b> · {guide.text} Codex의 요청만 믿지 않고 Hook·Process·File Sensor가 확인한 실제 실행 사실을 이해하기 쉽게 안내합니다.</p>
          <div className="guardian-guide-states" aria-label="가디언 상태 미리보기">
            {(['normal', 'review', 'blocked', 'recovery'] as const).map((state) => <button key={state} type="button" className={guideState === state ? 'is-active' : ''} onClick={() => setGuideState(state)}>{({ normal: '정상', review: '확인', blocked: '차단', recovery: '복구' })[state]}</button>)}
          </div>
        </div>
      )}
    </aside>
  )
}

export { TITLES as SIDEBAR_VIEW_TITLES }
