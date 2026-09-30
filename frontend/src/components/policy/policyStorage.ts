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
