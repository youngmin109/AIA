import { Button } from '../common/Button'
import { Icon } from '../common/Icon'
import { RoundAction } from '../common/Glass'
import { useShellStore } from '../../state/shellStore'
import { CodexConversationPane } from '../terminal/CodexConversationPane'
import { ResultView } from '../results/ResultView'
import { useRunStatus } from '../../hooks/useRunStatus'
import { useProfiles } from '../../hooks/useProfiles'
import { elapsedLabel, useNow } from '../../hooks/useElapsed'
import { isSessionRunning } from '../../api/display'
import { startupView } from '../../api/startupStatus'
import { workspaceShortName } from '../shell/sessionLabel'
import { ProtectionPanel } from './ProtectionPanel'

const ENDED_STATUSES = new Set(['COMPLETED', 'ABORTED', 'FAILED'])

/** ⑤ Work view: the large Codex conversation and the protection panel. */
export function WorkView() {
  const { activeRunId, openNewRun, setView } = useShellStore()
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

  if (isEnded) {
    return <div className="work-result"><ResultView runId={activeRunId} /></div>
  }

  return (
    <div className="work-layout view-enter">
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
      <ProtectionPanel runId={activeRunId} status={status} live={live} />
    </div>
  )
}
