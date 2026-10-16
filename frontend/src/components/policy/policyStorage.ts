const DEFAULT_PROFILE_KEY = 'aia.defaultPolicyProfile'

export function readDefaultPolicyProfile(): string | null {
  try {
    return window.localStorage.getItem(DEFAULT_PROFILE_KEY)
  } catch {
    return null
  }
}

export function writeDefaultPolicyProfile(value: string) {
  try {
    window.localStorage.setItem(DEFAULT_PROFILE_KEY, value)
  } catch {
    // Per-viewer convenience only; ignore storage failures (private mode, etc).
  }
}
import type { PolicyDocument } from './policyModel'
import { apiGet } from '../../api/client.ts'

type StoredCustomPolicy = { path: string; document: PolicyDocument }

const CUSTOM_KEY = 'aia.customPolicy'
function asCustomPolicy(value: unknown): StoredCustomPolicy | null {
  const candidate = value as Partial<StoredCustomPolicy> | null
  return typeof candidate?.path === 'string' && candidate.document?.profile === 'CUSTOM' && Array.isArray(candidate.document?.rules)
    ? candidate as StoredCustomPolicy
    : null
}
export function readCustomPolicy(): StoredCustomPolicy | null {
  try {
    return asCustomPolicy(JSON.parse(localStorage.getItem(CUSTOM_KEY) ?? 'null'))
  } catch { return null }
}
export function writeCustomPolicy(value: StoredCustomPolicy) {
  localStorage.setItem(CUSTOM_KEY, JSON.stringify(value))
  window.dispatchEvent(new Event('aia:policy-updated'))
}

/**
 * The saved custom policy, also after an app restart: the desktop app opens
 * each launch with an empty WebView profile, so an empty browser copy is
 * filled from the one the local server remembers.
 */
export async function loadCustomPolicy(): Promise<StoredCustomPolicy | null> {
  const local = readCustomPolicy()
  if (local) return local
  try {
    const remembered = asCustomPolicy(await apiGet<unknown>('/api/policy/custom'))
    if (remembered) {
      try { writeCustomPolicy(remembered) } catch { /* still usable for this view */ }
    }
    return remembered
  } catch { return null }
}
