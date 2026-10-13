import { useEffect, useState } from 'react'
import { apiGet } from '../api/client'
import { needsAttention } from '../api/sessionTabs'

const NONE = new Set<string>()

/**
 * Background conversations waiting for the user.  Their requests time out,
 * so the tabs show them; the shown conversation draws its own cards.
 */
export function useSessionAttention(runIds: string[], intervalMs = 3_000): Set<string> {
  const [waiting, setWaiting] = useState<Set<string>>(() => new Set())
  const key = runIds.join(',')
  useEffect(() => {
    if (!key) return
    const ids = key.split(',')
    let cancelled = false
    const check = () => Promise.all(ids.map(id =>
      apiGet<Record<string, unknown>>(`/api/runs/${encodeURIComponent(id)}/codex/status`)
        .then(status => (needsAttention(status) ? id : null))
        .catch(() => null),
    )).then(found => { if (!cancelled) setWaiting(new Set(found.filter((id): id is string => id !== null))) })
    check()
    const timer = window.setInterval(check, intervalMs)
    return () => { cancelled = true; window.clearInterval(timer) }
  }, [key, intervalMs])
  return key ? waiting : NONE
}
