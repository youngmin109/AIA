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

const CUSTOM_KEY = 'aia.customPolicy'
export function readCustomPolicy(): { path: string; document: PolicyDocument } | null {
  try {
    const value = JSON.parse(localStorage.getItem(CUSTOM_KEY) ?? 'null')
    return typeof value?.path === 'string' && value.document?.profile === 'CUSTOM' && Array.isArray(value.document?.rules) ? value : null
  } catch { return null }
}
export function writeCustomPolicy(value: { path: string; document: PolicyDocument }) {
  localStorage.setItem(CUSTOM_KEY, JSON.stringify(value))
  window.dispatchEvent(new Event('aia:policy-updated'))
}
