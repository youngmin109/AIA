import { apiGet, apiPost } from './client.ts'

export const UI_PREFERENCE_KEYS = [
  'aia.glass',
  'aia.motion',
  'aia.tint',
  'aia.pet',
  'aia.pet.position',
  'aia.pet.size',
  'aia.defaultPolicyProfile',
  'aia.ackedIncidents',
] as const

export type UiPreferenceKey = typeof UI_PREFERENCE_KEYS[number]
export const UI_PREFERENCE_RESTORED_EVENT = 'aia:preference-restored'

const allowedKeys = new Set<string>(UI_PREFERENCE_KEYS)
const pendingWrites = new Map<UiPreferenceKey, string>()
let writeTimer: ReturnType<typeof setTimeout> | undefined
let writeFlight: Promise<void> | undefined
let hydrating = 0

/** Queue one local setting for the server without making the UI wait for it. */
export function queueUiPreferenceWrite(key: UiPreferenceKey, value: string): void {
  if (hydrating || !allowedKeys.has(key) || typeof value !== 'string') return
  pendingWrites.set(key, value)
  if (writeTimer) clearTimeout(writeTimer)
  writeTimer = setTimeout(() => { void flushUiPreferenceWrites() }, 300)
}

/** Drain pending settings in order; failures stay local and never reach the UI. */
export function flushUiPreferenceWrites(): Promise<void> {
  if (writeTimer) clearTimeout(writeTimer)
  writeTimer = undefined
  if (writeFlight) return writeFlight
  writeFlight = (async () => {
    while (pendingWrites.size) {
      const batch = [...pendingWrites.entries()]
      pendingWrites.clear()
      for (const [key, value] of batch) {
        try { await apiPost('/api/ui-preferences', { key, value }) } catch { /* preferences are best-effort */ }
      }
    }
  })().finally(() => { writeFlight = undefined })
  return writeFlight
}

/** Restore only keys missing in this WebView and let each owning UI re-apply. */
export async function restoreUiPreferences(onApply: (key: UiPreferenceKey) => void): Promise<void> {
  let values: unknown
  try { values = await apiGet<unknown>('/api/ui-preferences') } catch { return }
  if (!values || typeof values !== 'object' || Array.isArray(values)) return

  for (const key of UI_PREFERENCE_KEYS) {
    if (!Object.hasOwn(values, key)) continue
    const value = (values as Record<string, unknown>)[key]
    if (!allowedKeys.has(key) || typeof value !== 'string') continue

    let localValue: string | null
    try { localValue = localStorage.getItem(key) } catch { continue }
    if (localValue !== null) {
      queueUiPreferenceWrite(key, localValue)
      continue
    }

    try { localStorage.setItem(key, value) } catch { continue }
    hydrating += 1
    try { onApply(key) } catch { /* a preference must not interrupt startup */ }
    finally { hydrating -= 1 }
    try {
      window.dispatchEvent(new CustomEvent(UI_PREFERENCE_RESTORED_EVENT, { detail: key }))
    } catch { /* the next render still reads the restored local value */ }
  }
}
