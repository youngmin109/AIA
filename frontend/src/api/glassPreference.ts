export type GlassPreference = 'on' | 'off'

export function normalizeGlassPreference(value: string | null): GlassPreference {
  return value === 'off' ? 'off' : 'on'
}

export function readGlassPreference(): GlassPreference {
  try { return normalizeGlassPreference(localStorage.getItem('aia.glass')) } catch { return 'on' }
}

/** Turning glass off drops the blur and refraction filters for slower PCs; protection is unaffected. */
export function applyGlassPreference(value: GlassPreference): void {
  document.documentElement.dataset.glass = value
  try { localStorage.setItem('aia.glass', value) } catch { /* keep the in-memory choice */ }
}
