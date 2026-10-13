import { useEffect, useState } from 'react'
import { codexModels } from '../api/endpoints'
import type { PermissionProfile } from '../api/permissionMode'

/** Codex's permission profiles (permissionProfile/list), read with the model list; empty when unknown. */
export function usePermissionProfiles(enabled = true): PermissionProfile[] {
  const [profiles, setProfiles] = useState<PermissionProfile[]>([])
  useEffect(() => {
    if (!enabled) return
    let cancelled = false
    codexModels()
      .then(result => { if (!cancelled) setProfiles(result.permission_profiles ?? []) })
      .catch(() => { if (!cancelled) setProfiles([]) })
    return () => { cancelled = true }
  }, [enabled])
  return profiles
}
