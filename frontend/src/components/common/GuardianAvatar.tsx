import guardianNormal from '../../assets/mascot/guardian-normal.png'
import guardianReview from '../../assets/mascot/guardian-review.png'
import guardianBlocked from '../../assets/mascot/guardian-blocked.png'
import guardianRecovery from '../../assets/mascot/guardian-recovery.png'
import type { GuardianState } from '../../api/guardianStatus'

const IMAGES = { normal: guardianNormal, review: guardianReview, blocked: guardianBlocked, recovery: guardianRecovery }

/** Decorative movement follows real display state; it confers no authority. */
export function GuardianAvatar({ state, alt, size = 'hero' }: { state: GuardianState; alt: string; size?: 'hero' | 'guide' | 'sidebar' }) {
  return <span className={`guardian-avatar guardian-avatar-${size} is-${state}`}>
    <span className="guardian-aura" aria-hidden="true" />
    <span className="guardian-orbit-ring" aria-hidden="true" />
    <span className="guardian-spark spark-one" aria-hidden="true" />
    <span className="guardian-spark spark-two" aria-hidden="true" />
    <img key={state} src={IMAGES[state]} alt={alt} />
  </span>
}
