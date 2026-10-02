export type MotionPreference = 'auto' | 'full' | 'reduced'
export function normalizeMotionPreference(value: string | null): MotionPreference {
  return value === 'full' || value === 'reduced' ? value : 'auto'
}
export function readMotionPreference(): MotionPreference {
  try { return normalizeMotionPreference(localStorage.getItem('aia.motion')) } catch { return 'auto' }
}
