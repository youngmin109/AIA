import guardianNormal from '../../assets/mascot/guardian-normal.png'
import guardianReview from '../../assets/mascot/guardian-review.png'
import guardianBlocked from '../../assets/mascot/guardian-blocked.png'
import guardianRecovery from '../../assets/mascot/guardian-recovery.png'
import { useGuardianState, type GuardianState } from '../../hooks/useGuardianState'

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

export function GuardianHero() {
  const guardian = useGuardianState()

  return (
    <article className={`card guardian-hero is-${guardian.state}`}>
      <div className="guardian-hero-head">
        <span className="guardian-hero-overline">{guardian.overline}</span>
        <span className={`guardian-hero-status is-${guardian.state}`}>아이아 가디언</span>
      </div>
      <div className="guardian-hero-main">
        <img className="guardian-hero-img" src={MASCOT[guardian.state]} alt={ALT[guardian.state]} />
        <div className="guardian-hero-copy">
          <h2>{guardian.headline}</h2>
          <p>{guardian.detail}</p>
        </div>
      </div>
    </article>
  )
}
