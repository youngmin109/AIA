import type { GuardianState } from '../../api/guardianStatus'
import { GUARDIAN_IMAGES } from './guardianImages'

/** Decorative movement follows real display state; it confers no authority. */
export function GuardianAvatar({ state, alt, size = 'hero' }: { state: GuardianState; alt: string; size?: 'hero' | 'guide' | 'pet' }) {
  return <span className={`guardian-avatar guardian-avatar-${size} is-${state}`}>
    <span className="guardian-aura" aria-hidden="true" />
    <span className="guardian-orbit-ring" aria-hidden="true" />
    <span className="guardian-spark spark-one" aria-hidden="true" />
    <span className="guardian-spark spark-two" aria-hidden="true" />
    <img key={state} src={GUARDIAN_IMAGES[state]} alt={alt} />
  </span>
}

/** Large floating guardian for glass hero cards. */
export function GuardianFigure({ state, alt, className }: { state: GuardianState; alt: string; className?: string }) {
  return <img key={state} className={`guardian-figure${className ? ` ${className}` : ''}`} src={GUARDIAN_IMAGES[state]} alt={alt} />
}
