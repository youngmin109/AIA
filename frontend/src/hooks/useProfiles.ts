import { useEffect, useState } from 'react'
import { listProfiles, type PolicyProfile } from '../api/endpoints'

let cached: PolicyProfile[] | null = null
let inflight: Promise<PolicyProfile[]> | null = null

function loadProfiles(): Promise<PolicyProfile[]> {
  if (cached) return Promise.resolve(cached)
  inflight ??= listProfiles().then(value => { cached = value; return value }).finally(() => { inflight = null })
  return inflight
}

/** Policy profiles change only with a new build, so one shared request is enough. */
export function useProfiles(): { profiles: PolicyProfile[]; error: boolean } {
  const [profiles, setProfiles] = useState<PolicyProfile[]>(cached ?? [])
  const [error, setError] = useState(false)
  useEffect(() => {
    let alive = true
    loadProfiles().then(value => { if (alive) setProfiles(value) }).catch(() => { if (alive) setError(true) })
    return () => { alive = false }
  }, [])
  return { profiles, error }
}
