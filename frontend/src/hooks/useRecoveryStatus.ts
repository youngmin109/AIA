import { useCallback, useEffect, useState } from 'react'
import { apiGet } from '../api/client'
import type { RecoveryStatusView } from '../api/resultTypes'
export function useRecoveryStatus(sessionId: string) {
  const [snapshot, setSnapshot] = useState<{ id: string; data: RecoveryStatusView | null; error: string | null } | null>(null)
  const [reloadToken, setReloadToken] = useState(0)
  const reload = useCallback(() => setReloadToken(value => value + 1), [])
  useEffect(() => {
    const controller = new AbortController()
    apiGet<RecoveryStatusView>(`/api/runs/${encodeURIComponent(sessionId)}/recovery`, controller.signal)
      .then(data => { if (!controller.signal.aborted) setSnapshot({ id: sessionId, data, error: null }) })
      .catch(error => { if (!controller.signal.aborted) setSnapshot({ id: sessionId, data: null, error: error instanceof Error ? error.message : String(error) }) })
    return () => controller.abort()
  }, [sessionId, reloadToken])
  const current = snapshot?.id === sessionId ? snapshot : null
  return { data: current?.data ?? null, error: current?.error ?? null, reload }
}
