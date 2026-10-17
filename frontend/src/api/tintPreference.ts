import { queueUiPreferenceWrite } from './preferenceSync.ts'

export type TintPreference = 'violet' | 'indigo' | 'teal'

export const TINT_OPTIONS: Array<{ value: TintPreference; label: string }> = [
  { value: 'violet', label: '보라' },
  { value: 'indigo', label: '남색' },
  { value: 'teal', label: '청록' },
]

export function normalizeTintPreference(value: string | null): TintPreference {
  return value === 'indigo' || value === 'teal' ? value : 'violet'
}

export function readTintPreference(): TintPreference {
  try { return normalizeTintPreference(localStorage.getItem('aia.tint')) } catch { return 'violet' }
}

/** Per-viewer look only; it never changes protection behavior. */
export function applyTintPreference(tint: TintPreference): void {
  document.documentElement.dataset.tint = tint
  try { localStorage.setItem('aia.tint', tint); queueUiPreferenceWrite('aia.tint', tint) } catch { /* private mode: keep the in-memory choice */ }
}
