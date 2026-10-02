import { GuardianAvatar } from '../common/GuardianAvatar'
import { useRunStatus } from '../../hooks/useRunStatus'
import { isSessionRunning } from '../../api/display'
import { useGuardianState, type GuardianState } from '../../hooks/useGuardianState'
import { useShellStore } from '../../state/shellStore'

const ALT: Record<GuardianState, string> = {
  normal: '정상 상태의 AIA 가디언',
  review: '확인 요청 상태의 AIA 가디언',
  blocked: '차단 상태의 AIA 가디언',
  recovery: '복구 완료 상태의 AIA 가디언',
}

/** Compact status card: the one place the Guardian mascot appears on the dashboard. */
export function GuardianHero({ readiness, ready }: { readiness: string; ready: boolean }) {
  const guardian = useGuardianState()
  const { activeRunId, openSettingsModal, setView } = useShellStore()
  const { data: status } = useRunStatus(activeRunId)
  const isLive = isSessionRunning(status?.session?.status, Boolean(status?.runtime_reconciliation?.orphaned))

  return (
    <article className={`card guardian-hero is-${guardian.state}`}>
      <div className="guardian-hero-main">
        <GuardianAvatar state={guardian.state} alt={ALT[guardian.state]} />
        <div className="guardian-hero-copy"><small className="guardian-introduction">아이아 가디언 · 작업을 지켜보는 보호 안내자</small>
          <div className="guardian-hero-chips">
            <span className={`guardian-hero-status is-${guardian.state}`}>{guardian.label}</span>
            <span className={`guardian-hero-readiness${ready ? ' is-ready' : ''}`}>{readiness}</span>
          </div>
          <h2>{guardian.headline}</h2>
          <p>{guardian.detail}</p>
          {!activeRunId ? (
            <button type="button" className="guardian-start-button" onClick={openSettingsModal}>보호 실행 시작</button>
          ) : (
            <button type="button" className="guardian-start-button" onClick={() => setView(isLive ? 'terminal' : 'audit')}>{isLive ? guardian.label === '사용자 확인' ? '확인 요청 열기' : '에이전트 작업 열기' : '결과·복구 확인'}</button>
          )}
        </div>
      </div>
    </article>
  )
}
