import { Icon } from '../common/Icon'
import { useShellStore } from '../../state/shellStore'
import { CodexConversationPane } from '../terminal/CodexConversationPane'
import { ResultView } from '../results/ResultView'
import { useRunStatus } from '../../hooks/useRunStatus'
import { sessionDisplayName } from './sessionLabel'

const ENDED_STATUSES = new Set(['COMPLETED', 'ABORTED', 'FAILED'])

export function ActiveRunPane() {
  const { activeRunId, clearActiveRun, openSettingsModal, rightPanelCollapsed, toggleRightPanel } = useShellStore()
  const { data: status } = useRunStatus(activeRunId, { enabled: Boolean(activeRunId) })

  const sessionStatus = status?.session?.status
  const isEnded = Boolean(sessionStatus && ENDED_STATUSES.has(sessionStatus))
  // Wait for the run's launch mode before connecting to its app-server session.
  const launchMode = status ? status.session?.launch_mode ?? (status.launch_mode as string | undefined) ?? 'inherit' : null

  return (
    <div className="center-pane">
      <div className="tab-strip">
        {activeRunId && (
          <div className="tab-item is-active">
            <span>{sessionDisplayName(status?.session?.workspace)}</span>
            <span
              role="button"
              tabIndex={-1}
              className="tab-item-close"
              onClick={clearActiveRun}
              title="닫기"
            >
              <Icon name="close" size={12} />
            </span>
          </div>
        )}
        <button type="button" className="tab-strip-action" title="새 보호 실행" onClick={openSettingsModal}>
          <Icon name="plus" size={16} />
        </button>
        <div className="tab-strip-spacer" />
        <button
          type="button"
          className={`tab-strip-action${rightPanelCollapsed ? '' : ' is-active'}`}
          title={rightPanelCollapsed ? '실시간 기록 패널 펼치기' : '실시간 기록 패널 접기'}
          aria-pressed={!rightPanelCollapsed}
          onClick={toggleRightPanel}
        >
          <Icon name="results" size={16} />
        </button>
      </div>
      <div className="center-content">
        {activeRunId ? (
          isEnded ? (
            <ResultView runId={activeRunId} />
          ) : (
            <div className="terminal-grid">
              <div className="terminal-card">
                {launchMode === null ? (
                  <div className="codex-transcript">
                    <div className="codex-row codex-notice is-info">보호 실행 정보를 불러오는 중입니다…</div>
                  </div>
                ) : launchMode === 'codex_app_server' ? (
                  <CodexConversationPane key={activeRunId} runId={activeRunId} runEnded={isEnded} />
                ) : (
                  <div className="codex-transcript">
                    <div className="codex-row codex-notice is-info">이 실행은 이전 터미널 방식으로 시작되어 실시간 대화를 다시 연결할 수 없습니다. 완료된 실행 결과는 감사 기록에서 확인할 수 있습니다.</div>
                  </div>
                )}
              </div>
            </div>
          )
        ) : (
          <div className="center-empty-state">
            <strong>열린 실행이 없습니다</strong>
            <p>좌측 지난 실행 목록에서 항목을 선택하거나, + 버튼으로 새 보호 실행을 시작하세요.</p>
          </div>
        )}
      </div>
    </div>
  )
}
