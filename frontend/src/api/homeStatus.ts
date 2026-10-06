import type { PreflightCheck } from '../hooks/usePreflight'

export type PillarState = 'ready' | 'setup' | 'checking'

const BLOCKING_CHECKS = ['pretool_hook', 'codex_hook_trust', 'hook_verification']

/**
 * Pre-execution blocking can be checked before a run (Hook installed, trusted,
 * delivery verified). Monitoring and recovery start only inside a run, so the
 * home screen never calls them "ready" ahead of time.
 */
export function blockingPillar(checks?: PreflightCheck[] | null): PillarState {
  if (!checks) return 'checking'
  const relevant = checks.filter(check => BLOCKING_CHECKS.includes(check.name))
  if (relevant.length === 0) return 'checking'
  return relevant.every(check => check.ok) ? 'ready' : 'setup'
}

export function recoveryPillar(checks?: PreflightCheck[] | null): PillarState {
  const controlRoot = checks?.find(check => check.name === 'control_root')
  if (!controlRoot) return 'checking'
  return controlRoot.ok ? 'ready' : 'setup'
}

/** "4:05" under an hour, "1:04:05" after. */
export function formatElapsed(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000))
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const seconds = String(total % 60).padStart(2, '0')
  return hours > 0 ? `${hours}:${String(minutes).padStart(2, '0')}:${seconds}` : `${minutes}:${seconds}`
}
