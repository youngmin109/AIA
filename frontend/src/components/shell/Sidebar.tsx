import { createPortal } from 'react-dom'
import { useDialog } from '../common/useDialog'
import { displayStatus } from '../../api/display'
import { errorReportTemplate } from '../../api/errorReport'
import { useState } from 'react'
import { Icon, type IconName } from '../common/Icon'
import { useShellStore, type ShellView } from '../../state/shellStore'
import { GuardianAvatar } from '../common/GuardianAvatar'
import { useGuardianState } from '../../hooks/useGuardianState'
import { sidebarSessions, sessionDestination, sessionStateLabel } from '../../api/sessionNavigation'
import { useRunStatus } from '../../hooks/useRunStatus'
import { isRunActive, useRunList } from '../../hooks/useRunList'
import { sessionCreatedLabel, sessionDisplayName, sessionShortId, workspaceShortName } from './sessionLabel'

const NAV_ITEMS: Array<{ view: ShellView; icon: IconName; label: string }> = [
  { view: 'dashboard', icon: 'dashboard', label: '보호 현황' },
  { view: 'terminal', icon: 'terminal', label: '보호 실행' },
  { view: 'policy', icon: 'shield', label: '정책' },
  { view: 'audit', icon: 'search', label: '증거' },
  { view: 'settings', icon: 'settings', label: '설정' },
]

const TITLES: Record<ShellView, string> = {
  dashboard: '보호 현황',
  agents: '에이전트',
  terminal: '보호 실행',
  policy: '정책 관리',
  audit: '증거 탐색',
  reports: '보안 보고서',
  settings: '제품 설정',
}

export function Sidebar() {
  const { activeView, sidebarCollapsed, setView, activeRunId, setActiveRun, openSettingsModal } = useShellStore()
  const [guideOpen, setGuideOpen] = useState(false)
  const guideRef = useDialog(guideOpen, () => setGuideOpen(false))
  const [guideTopic, setGuideTopic] = useState<'start' | 'hook' | 'safety' | 'recovery' | 'report'>('start')
  const [reportCopied, setReportCopied] = useState(false)
  const { data: status } = useRunStatus(activeRunId, { enabled: Boolean(activeRunId) })
  const { data: runs, error: runsError, isLoading: runsLoading, refetch: refreshRuns } = useRunList()
  const guardian = useGuardianState()
  const allOpenRuns = (runs ?? []).filter(isRunActive)
  const recentRuns = sidebarSessions(runs ?? [], activeRunId)
  const guideContent = {
    start: {
      title: '보호 실행을 시작할까요?',
      text: '작업공간과 정책을 고른 뒤 시작하면, 아이아가 Codex의 요청과 실제 파일·프로세스 변화를 함께 관찰해요.',
      steps: ['보호 세팅에서 Hook 연결 상태를 확인해요.', '폴더 선택으로 작업할 폴더를 고릅니다.', '정책을 고르고 보호 실행을 시작한 뒤 보호 실행 화면에 요청을 입력해요.'],
    },
    hook: {
      title: 'Hook 연결은 왜 필요한가요?',
      text: 'Hook은 Codex가 도구를 실행하기 직전 AIA에 알려 주는 연결 지점이에요. 신뢰 여부는 Codex 안에서 사용자가 직접 결정합니다.',
      steps: ['AIA에서 Hook 설치를 누릅니다.', '새 터미널에서 codex를 실행한 뒤 /hooks를 엽니다.', 'AIA Hook을 검토하고 Trust한 다음, AIA에서 연결 검증을 누릅니다.'],
    },
    safety: {
      title: '위험 알림이 뜨면 이렇게 보세요',
      text: '명령, 대상 경로, 위험 이유를 먼저 확인하세요. AIA가 의미를 해석하지 못하는 지원 범위 밖 도구만 사용자 확인을 요청할 수 있고, 정책상 금지된 행위는 사용자가 허용할 수 없습니다.',
      steps: ['요청된 명령과 대상 파일 경로를 확인합니다.', '위험 이유와 적용된 정책을 읽습니다.', '지원 범위 밖 도구라면 이번만 허용하거나 거절한 뒤, 결과를 감사 기록에서 확인합니다.'],
    },
    recovery: {
      title: '복구와 감사 기록은 어떻게 보나요?',
      text: '복구가 필요한 경우 AIA는 실행 전 기준점을 바탕으로 처리하고, 파일 경로와 SHA-256 무결성 검증 결과를 감사 기록에 남깁니다.',
      steps: ['감사 기록에서 끝난 실행을 선택합니다.', '증거와 정책 판단, 실행 결과를 순서대로 확인합니다.', '복구·무결성 검증 결과가 확정된 뒤 결과 번들을 확인합니다.'],
    },
    report: {
      title: '문제가 생겼나요?',
      text: '오류를 보내기 전에 실행 중인 작업이 있다면 먼저 중지 또는 결과 확정을 확인하세요. 아래 버튼은 내용을 자동 전송하지 않고, 신고 초안만 복사하거나 GitHub 이슈 작성 화면을 엽니다.',
      steps: ['무엇을 하려 했는지와 실제로 보인 현상을 적습니다.', '오류가 난 시각, 화면 캡처, 실행 상태를 함께 남깁니다.', '비밀값·API 키·개인 경로는 신고 내용에서 지웁니다.'],
    },
  }[guideTopic]

  function handleNavClick(view: ShellView) {
    setView(view)
  }

  function openRun(run: typeof recentRuns[number]) {
    setActiveRun(run.session_id)
    setView(sessionDestination(run))
  }

  function guideAction(view: ShellView) {
    setGuideOpen(false)
    setView(view)
  }

  async function copyErrorReport() {
    try {
      if (!navigator.clipboard) throw new Error('클립보드를 사용할 수 없습니다.')
      await navigator.clipboard.writeText(errorReportTemplate())
      setReportCopied(true)
    } catch {
      setReportCopied(false)
    }
  }

  function openIssueDraft() {
    const params = new URLSearchParams({ title: '[오류 신고] ', body: errorReportTemplate() })
    window.open(`https://github.com/youngmin109/AIA/issues/new?${params.toString()}`, '_blank', 'noopener,noreferrer')
  }

  return (
    <aside className={`app-sidebar${sidebarCollapsed ? ' is-collapsed' : ''}`}>
      <div className="app-sidebar-brand">
        <span className="app-sidebar-brandmark">
          <Icon name="brand" size={18} />
        </span>
        <span className="app-sidebar-brand-name">
          AIA Guardian
          <small>에이전트 보호 실행</small>
        </span>

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
      <section className="sidebar-sessions" aria-label="보호 세션 목록">
        <div className="sidebar-section-head">
          <span>보호 세션 <small>{allOpenRuns.length}개 진행 중</small></span>
          <button type="button" title="새 보호 실행" onClick={openSettingsModal}><Icon name="plus" size={14} /></button>
        </div>
        {runsError && <div className="sidebar-session-notice" role="alert">목록 갱신 실패 · 이전 기록일 수 있어요.<button type="button" onClick={refreshRuns}>다시 불러오기</button></div>}
        <div className="sidebar-session-list">
        {recentRuns.length > 0 ? recentRuns.map((run) => (
          <button
            key={run.session_id}
            type="button"
            className={`sidebar-session${activeRunId === run.session_id ? ' is-active' : ''}`}
            onClick={() => openRun(run)}
            aria-current={activeRunId === run.session_id ? 'true' : undefined}
            title={run.workspace ?? '작업공간 확인 중'}
          >
            <span className={`session-indicator${isRunActive(run) ? ' is-live' : ''}`} aria-hidden="true" />
            <span><b>{sessionDisplayName(run.workspace)}</b><small>{sessionStateLabel(run)}</small><small>{sessionCreatedLabel(run.created_at)} · {sessionShortId(run.session_id)}</small></span>
          </button>
        )) : <p className="sidebar-session-empty">{runsLoading ? '보호 세션을 불러오고 있어요…' : runsError ? '세션 목록을 확인할 수 없습니다.' : '이 기록 폴더에는 아직 세션이 없어요. + 버튼으로 보호 실행을 시작하세요.'}</p>}
        </div>
        {Boolean(runs?.length) && <button type="button" className="sidebar-all-sessions" onClick={() => setView('audit')}>전체 기록 보기 ({runs?.length}) <Icon name="history" size={13} /></button>}
      </section>
      <button type="button" className="sidebar-guardian" onClick={() => { setGuideTopic(!activeRunId ? 'start' : guardian.state === 'blocked' || guardian.label === '사용자 확인' ? 'safety' : status?.session?.status === 'COMPLETED' || status?.session?.status === 'ABORTED' ? 'recovery' : 'start'); setGuideOpen(true) }} title="아이아 가디언 도움말" aria-expanded={guideOpen}>
        <GuardianAvatar state={guardian.state} alt="" size="sidebar" />
        <span><b>아이아 가디언</b><small>도움말 · 상태 안내 · 오류 신고</small></span>
      </button>
      <section className="sidebar-workspace" aria-label="현재 보호 실행">
        <span>현재 보호 실행</span>
        <b title={status?.session?.workspace ?? undefined}>{status?.session?.workspace ? workspaceShortName(status.session.workspace) : '선택된 작업공간 없음'}</b>
        <small>{activeRunId ? `${sessionDisplayName(status?.session?.workspace)} · ${displayStatus(status?.session?.status)}` : '보호 실행 시작 전'}</small>
      </section>
      {guideOpen && createPortal(
        <div ref={guideRef} tabIndex={-1} className="guardian-guide-popover" role="dialog" aria-modal="true" aria-label="아이아 가디언 도움말">
          <button type="button" className="icon-button guardian-guide-close" onClick={() => setGuideOpen(false)} aria-label="도움말 닫기"><Icon name="close" size={14} /></button>
          <div className="guardian-guide-hero">
            <GuardianAvatar state={guardian.state} alt={`아이아 가디언 · ${guardian.label}`} size="guide" />
            <div><strong>안녕하세요, 아이아 가디언이에요.</strong><p>준비된 안내를 골라보세요. 저는 에이전트가 아니라 Codex의 실제 실행과 AIA의 보호 상태를 설명하는 안내자예요.</p></div>
          </div>
          <div className={`guardian-current-state is-${guardian.state}`}><span>현재 상태 · {guardian.label}</span><strong>{guardian.headline}</strong><p>{guardian.detail}</p></div>
          <div className="guardian-guide-topics" aria-label="도움 주제">
            {([
              ['start', '시작하기'], ['hook', 'Hook 연결'], ['safety', '위험 알림'], ['recovery', '복구·감사'], ['report', '오류 신고'],
            ] as const).map(([topic, label]) => <button key={topic} type="button" className={guideTopic === topic ? 'is-active' : ''} onClick={() => { setGuideTopic(topic); setReportCopied(false) }}>{label}</button>)}
          </div>
          <section key={guideTopic} className="guardian-guide-answer" aria-live="polite">
            <b>{guideContent.title}</b>
            <p>{guideContent.text}</p>
            <ol className="guardian-guide-flow">{guideContent.steps.map((step) => <li key={step}>{step}</li>)}</ol>
            {guideTopic === 'report' && <div className="guardian-report-actions">
              <button type="button" className="secondary-button" onClick={copyErrorReport}>{reportCopied ? '신고 초안을 복사했어요' : '신고 초안 복사'}</button>
              <button type="button" className="cta-button" onClick={openIssueDraft}>GitHub 이슈 작성</button>
            </div>}
            {guideTopic === 'start' && <button type="button" className="cta-button" onClick={() => { setGuideOpen(false); openSettingsModal() }}>새 보호 실행 설정</button>}
            {guideTopic === 'hook' && <button type="button" className="cta-button" onClick={() => { setGuideOpen(false); openSettingsModal() }}>Hook 설치·연결 검증 열기</button>}
            {guideTopic === 'safety' && <button type="button" className="cta-button" onClick={() => guideAction(guardian.label === '사용자 확인' ? 'terminal' : 'audit')}>{guardian.label === '사용자 확인' ? '실제 확인 요청 열기' : '정책 사건·증거 확인'}</button>}
            {guideTopic === 'recovery' && <button type="button" className="cta-button" onClick={() => guideAction('audit')}>{activeRunId ? '선택한 실행 결과·복구 열기' : '복구할 실행 기록 선택'}</button>}
          </section>
          <p className="guardian-authority-note">가디언은 안내자예요. 여기서 실행을 허용·차단하거나 자동 복구하지 않습니다.</p>
        </div>, document.body
      )}
    </aside>
  )
}

export { TITLES as SIDEBAR_VIEW_TITLES }
