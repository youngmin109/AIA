import guardianNormal from '../../assets/mascot/guardian-normal.png'
import guardianReview from '../../assets/mascot/guardian-review.png'
import guardianBlocked from '../../assets/mascot/guardian-blocked.png'
import guardianRecovery from '../../assets/mascot/guardian-recovery.png'
import { useGuardianState, type GuardianState } from '../../hooks/useGuardianState'
import { useShellStore } from '../../state/shellStore'

const MASCOT: Record<GuardianState, string> = {
  normal: guardianNormal,
  review: guardianReview,
  blocked: guardianBlocked,
  recovery: guardianRecovery,
}

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

  return (
    <article className={`card guardian-hero is-${guardian.state}`}>
      <div className="guardian-hero-main">
        <img key={guardian.state} className="guardian-hero-img" src={MASCOT[guardian.state]} alt={ALT[guardian.state]} />
        <div className="guardian-hero-copy">
          <div className="guardian-hero-chips">
            <span className={`guardian-hero-status is-${guardian.state}`}>{guardian.label}</span>
            <span className={`guardian-hero-readiness${ready ? ' is-ready' : ''}`}>{readiness}</span>
          </div>
          <h2>{guardian.headline}</h2>
          <p>{guardian.detail}</p>
          {!activeRunId ? (
            <button type="button" className="guardian-start-button" onClick={openSettingsModal}>보호 실행 시작</button>
          ) : (
            <button type="button" className="guardian-start-button" onClick={() => setView('terminal')}>Agent CLI 열기</button>
          )}
        </div>
      </div>
    </article>
  )
}
