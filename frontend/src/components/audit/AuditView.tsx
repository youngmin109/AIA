import { useState } from 'react'
import { Button } from '../common/Button'
import { Icon } from '../common/Icon'
import { StatTile, GlossyIcon } from '../common/Glass'
import { useShellStore } from '../../state/shellStore'
import { useRunList } from '../../hooks/useRunList'
import { ResultView } from '../results/ResultView'
import { RecoveryPoints } from '../results/RecoveryPoints'
import type { RunSummary } from '../../api/types'
import { filterRuns, historyState, historyStateLabel, type HistoryFilter } from '../../api/historyFilter'
import { failedBeforeResult, stoppedWhilePreparing } from '../../api/sessionNavigation'
import { useRunSnapshot } from '../../hooks/useRunSnapshot'
import { StartupFailurePanel } from '../work/StartupFailurePanel'
import { sessionCreatedLabel, sessionShortId, workspaceShortName } from '../shell/sessionLabel'

const FILTERS: Array<[HistoryFilter, string]> = [['all', '전체'], ['review', '확인 필요'], ['ok', '정상']]
const STATE_TONE = { live: 'ok', review: 'warn', ok: 'ok', failed: 'bad', orphaned: 'warn' } as const
const PILL_TONE = { live: 'good', review: 'warning', ok: 'good', failed: 'bad', orphaned: 'warning' } as const

/** ⑨ History: every protected run; a row opens its result (③). */
export function AuditView() {
  const { activeRunId, historyRunId, openResult, closeResult, setView } = useShellStore()
  const { data: runs, isLoading, error, refetch } = useRunList()
  const [filter, setFilter] = useState<HistoryFilter>('all')
  const all = runs ?? []
  const selected = all.find(run => run.session_id === historyRunId) ?? null

  if (selected) {
    return <HistoryDetail run={selected} onBack={closeResult} onOpenWork={() => setView('work')} />
  }

  const visible = filterRuns(all, filter)
  const counts = { review: filterRuns(all, 'review').length, ok: filterRuns(all, 'ok').length }
  const live = all.filter(run => historyState(run) === 'live').length

  function open(run: RunSummary) {
    openResult(run.session_id)
  }

  return (
    <div className="page-stack history-page view-enter">
      <header className="page-head">
        <div>
          <h1>기록</h1>
          <p>지금까지 보호한 실행 {all.length}건</p>
        </div>
        <div className="segmented history-filters" role="group" aria-label="기록 필터">
          {FILTERS.map(([value, label]) => (
            <button key={value} type="button" aria-pressed={filter === value} onClick={() => setFilter(value)}>
              {label} <span className="history-filter-count">{value === 'all' ? all.length : counts[value]}</span>
            </button>
          ))}
        </div>
      </header>

      <section className="stat-grid history-summary" aria-label="요약">
        <StatTile label="전체 실행" value={all.length} note="이 PC의 기록" />
        <StatTile label="확인 필요" value={counts.review} tone={counts.review > 0 ? 'warning' : undefined} note="사건·검증 확인" />
        <StatTile label="실행 중" value={live} tone={live > 0 ? 'success' : undefined} note="작업창에서 이어가기" />
      </section>

      <section className="glass history-list" aria-label="실행 목록">
        {isLoading && !runs && <p className="faint-note">기록을 불러오는 중이에요…</p>}
        {error && <div className="glass-notice is-warning"><strong>기록을 새로 불러오지 못했어요</strong><Button variant="text" onClick={refetch}>다시 불러오기</Button></div>}
        {runs && visible.length === 0 && <div className="glass-empty"><strong>{all.length === 0 ? '아직 보호 실행 기록이 없어요' : '이 조건의 기록이 없어요'}</strong></div>}
        {visible.map(run => {
          const state = historyState(run)
          return (
            <button key={run.session_id} type="button" className={`history-row${run.session_id === activeRunId ? ' is-current' : ''}`} onClick={() => open(run)}>
              <span className={`status-dot is-${STATE_TONE[state]}`} aria-hidden="true" />
              <span className="history-row-main">
                <strong>{workspaceShortName(run.workspace)}</strong>
                <small>{sessionCreatedLabel(run.created_at)} · {sessionShortId(run.session_id)}</small>
              </span>
              <span className="history-row-chips">
                {(run.incident_count ?? 0) > 0 && <span className="badge is-bad">사건 {run.incident_count}</span>}
                {run.bundle_status === 'VALID' && <span className="badge is-neutral">기록 확인됨</span>}
              </span>
              <span className={`status-pill ${PILL_TONE[state]}`}>{historyStateLabel(run)}</span>
              <Icon name="arrowRight" size={16} />
            </button>
          )
        })}
        <div className="history-foot">
          <p className="faint-note">각 실행의 감사 기록은 파일마다 SHA-256 해시 목록으로 검증돼요. 기록은 데이터베이스가 아니라 이 PC의 기록 폴더에 실행마다 파일로 저장되고, 실행 전 기준점(작업 폴더 사본)도 함께 있어서 폴더가 클수록 용량이 커져요. 밖으로 보내지 않아요.</p>
          {typeof window.pywebview?.api?.open_records_folder === 'function' && (
            <Button variant="text" onClick={() => { window.pywebview?.api?.open_records_folder?.().catch(() => {}) }}><Icon name="folder" size={14} />기록 폴더 열기</Button>
          )}
        </div>
      </section>
    </div>
  )
}

function HistoryDetail({ run, onBack, onOpenWork }: { run: RunSummary; onBack: () => void; onOpenWork: () => void }) {
  const { openNewRun } = useShellStore()
  const state = historyState(run)
  const acknowledged = Boolean((run.runtime_reconciliation as { acknowledged?: boolean } | undefined)?.acknowledged)
  return (
    <div className="history-detail">
      <Button variant="text" className="history-back" onClick={onBack}><span className="history-back-arrow" aria-hidden="true"><Icon name="arrowRight" size={16} /></span>기록 목록</Button>
      {state === 'live' ? (
        <div className="glass is-soft work-empty">
          <GlossyIcon tone="success" icon="pulse" size="lg" />
          <strong>이 실행은 아직 진행 중이에요</strong>
          <span className="muted">대화와 실시간 보호 상태는 작업창에서 볼 수 있어요.</span>
          <Button variant="cta" onClick={onOpenWork}>작업창 열기</Button>
        </div>
      ) : stoppedWhilePreparing(run) ? (
        <div className="glass is-soft work-empty">
          <GlossyIcon tone="amber" icon="alert" size="lg" />
          <strong>준비하던 중에 앱이 닫혀 시작되지 않은 실행이에요</strong>
          <span className="muted">AIA가 기준점 저장이나 감시를 준비하던 중 앱이 닫혔어요. Codex는 시작되지 않았어요.{acknowledged ? ' 다시 열 때 정리 확인을 마쳤어요.' : ''} 같은 폴더로 새 보호 실행을 시작하면 돼요.</span>
          <Button variant="cta" onClick={openNewRun}>새 보호 실행</Button>
        </div>
      ) : state === 'orphaned' && !['COMPLETED', 'ABORTED', 'FAILED'].includes(String(run.status)) ? (
        <div className="glass is-soft work-empty">
          <GlossyIcon tone="amber" icon="alert" size="lg" />
          <strong>이전 실행의 연결이 끊겼어요</strong>
          <span className="muted">저장된 상태는 실행 중으로 남아 있지만 지금 대화를 다시 연결할 수 없어요. 새 보호 실행에서 같은 작업 폴더를 고르면 안전하게 정리할 수 있는지 확인해요. 살아 있는 프로세스를 자동으로 강제 종료하지 않아요.</span>
        </div>
      ) : failedBeforeResult(run) ? (
        <FailedRunDetail run={run} onRestart={openNewRun} />
      ) : (
        <ResultView runId={run.session_id} showEvidenceLog />
      )}
      {/* A run that failed before its result never made a checkpoint to restore. */}
      {!failedBeforeResult(run) && <RecoveryPoints key={run.session_id} runId={run.session_id} />}
    </div>
  )
}

function FailedRunDetail({ run, onRestart }: { run: RunSummary; onRestart: () => void }) {
  // The run list has no reason; the run's own status keeps it.
  const snapshot = useRunSnapshot(run.session_id)
  return <StartupFailurePanel error={snapshot?.error} workspace={run.workspace} onRestart={onRestart} />
}
