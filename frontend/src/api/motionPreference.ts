export type MotionPreference = 'auto' | 'full' | 'reduced'
export function normalizeMotionPreference(value: string | null): MotionPreference {
  return value === 'full' || value === 'reduced' ? value : 'auto'
}
export function readMotionPreference(): MotionPreference {
  try { return normalizeMotionPreference(localStorage.getItem('aia.motion')) } catch { return 'auto' }
}
/** Per-viewer motion choice; html[data-motion] drives the CSS kill switch. */
export function applyMotionPreference(value: MotionPreference): void {
  document.documentElement.dataset.motion = value
  try { localStorage.setItem('aia.motion', value) } catch { /* In-memory preference still works. */ }
}
