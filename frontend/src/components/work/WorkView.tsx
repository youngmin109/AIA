import { Button } from '../common/Button'
import { Icon } from '../common/Icon'
import { RoundAction, GlossyIcon } from '../common/Glass'
import { useShellStore } from '../../state/shellStore'
import { CodexConversationPane } from '../terminal/CodexConversationPane'
import { useRunStatus } from '../../hooks/useRunStatus'
import { useProfiles } from '../../hooks/useProfiles'
import { elapsedLabel, useNow } from '../../hooks/useElapsed'
import { isSessionRunning } from '../../api/display'
import { startupView } from '../../api/startupStatus'
import { StartupFailurePanel } from './StartupFailurePanel'
import { workspaceShortName } from '../shell/sessionLabel'
import { ProtectionPanel } from './ProtectionPanel'
import { SessionTabs } from './SessionTabs'
import { ThreatAlert } from './ThreatAlert'
import { useRunActions } from '../../hooks/useRunActions'
import { threatsOf } from '../../api/threats'
import { useMemo } from 'react'

const ENDED_STATUSES = new Set(['COMPLETED', 'ABORTED', 'FAILED'])

/** ⑤ Work view: the large Codex conversation and the protection panel. */
export function WorkView() {
  const { activeRunId, openNewRun, setView, openResult } = useShellStore()
  const { data: status } = useRunStatus(activeRunId, { enabled: Boolean(activeRunId) })
  const { profiles } = useProfiles()
  const sessionStatus = status?.session?.status
  const isEnded = Boolean(sessionStatus && ENDED_STATUSES.has(sessionStatus))
  const live = isSessionRunning(sessionStatus, status?.runtime_reconciliation?.orphaned)
  const now = useNow(live)
  const elapsed = elapsedLabel(status?.session?.created_at, now)
  // Wait for the run's launch mode before connecting to its app-server session.
  const launchMode = status ? status.session?.launch_mode ?? (status.launch_mode as string | undefined) ?? 'inherit' : null
  const policyName = profiles.find(profile => profile.value === status?.policy?.profile)?.display_name ?? status?.policy?.profile
  const { data: actions } = useRunActions(activeRunId, live)
  const threats = useMemo(() => threatsOf(actions), [actions])

  if (!activeRunId) {
    return (
      <div className="glass is-soft work-empty view-enter">
        <strong>열린 작업이 없어요</strong>
        <span className="muted">보호 실행을 시작하면 Codex와의 대화가 여기에 크게 보여요.</span>
        <RoundAction small onClick={openNewRun}>보호 시작</RoundAction>
        <Button variant="text" onClick={() => setView('history')}>지난 실행 보기 <Icon name="arrowRight" size={14} /></Button>
      </div>
    )
  }

  if (isEnded && sessionStatus === 'FAILED') {
    // A run that failed, often while preparing, must not read as a finished task.
    return (
      <>
      <SessionTabs />
      <StartupFailurePanel
        key={activeRunId}
        error={status?.error}
        workspace={status?.session?.workspace}
        onRestart={openNewRun}
        onOpenResult={status?.result_available ? () => openResult(activeRunId) : undefined}
      />
      </>
    )
  }

  if (isEnded) {
    return (
      <>
      <SessionTabs />
      <div className="glass is-soft work-empty work-ended view-enter" key={activeRunId}>
        <GlossyIcon tone="success" icon="check" size="lg" />
        <strong>작업이 끝났어요</strong>
        <span className="muted">보호 실행 결과와 '작업 폴더 되돌리기'는 <b>기록</b>에서 볼 수 있어요.</span>
        <Button variant="cta" onClick={() => openResult(activeRunId)}><Icon name="records" size={16} />기록에서 결과 보기</Button>
        <Button variant="text" onClick={openNewRun}><Icon name="plus" size={14} />새 대화 시작</Button>
      </div>
      </>
    )
  }

  return (
    <>
    <SessionTabs />
    <div className="work-layout view-enter" key={activeRunId}>
      <section className="glass is-hero work-chat" aria-label={`Codex 대화 · ${workspaceShortName(status?.session?.workspace)}`}>
        {launchMode === null ? (
          <div className="chat-empty"><strong>보호 실행 정보를 불러오는 중이에요…</strong></div>
        ) : launchMode === 'codex_app_server' ? (
          <CodexConversationPane
            key={activeRunId}
            runId={activeRunId}
            runEnded={isEnded}
            startup={startupView(status?.startup)}
            context={<>
              {policyName && <span className="chip is-small"><Icon name="shieldPlain" size={14} />{policyName}</span>}
              {elapsed && <span className="chip is-small chat-elapsed">{elapsed}</span>}
            </>}
          />
        ) : (
          <div className="chat-empty"><strong>이 실행은 이전 터미널 방식으로 시작돼 대화를 다시 연결할 수 없어요.</strong><span>끝난 뒤 결과는 기록에서 확인할 수 있어요.</span></div>
        )}
      </section>
      <ProtectionPanel runId={activeRunId} status={status} live={live} actions={actions} threats={threats} />
    </div>
    <ThreatAlert key={`alert-${activeRunId}`} threats={threats} fileCount={status?.activity?.unique_file_count ?? null} />
    </>
  )
}
