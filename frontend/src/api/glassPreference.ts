export type GlassPreference = 'on' | 'off'

/** Glass is off unless the viewer turned it on: the blur and refraction filters make slower PCs lag. */
export function normalizeGlassPreference(value: string | null): GlassPreference {
  return value === 'on' ? 'on' : 'off'
}

export function readGlassPreference(): GlassPreference {
  try { return normalizeGlassPreference(localStorage.getItem('aia.glass')) } catch { return 'off' }
}

/** Turning glass off drops the blur and refraction filters for slower PCs; protection is unaffected. */
export function applyGlassPreference(value: GlassPreference): void {
  document.documentElement.dataset.glass = value
  try { localStorage.setItem('aia.glass', value) } catch { /* keep the in-memory choice */ }
}
