import { useEffect, useState } from 'react'
import { apiGet } from '../api/client'
import type { ResultView } from '../api/resultTypes'

/** One-shot fetch (not polled -- a completed run's result is static).
 * Pass `enabled: false` to skip fetching, e.g. while a run is still active
 * and /result would just report it unavailable. */
export function useResult(sessionId: string, { enabled = true }: { enabled?: boolean } = {}) {
  const [snapshot, setSnapshot] = useState<{ id: string; value: ResultView } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [reloadToken, setReloadToken] = useState(0)
  useEffect(() => {
    const updated = (event: Event) => { if ((event as CustomEvent).detail === sessionId) setReloadToken(value => value + 1) }
    window.addEventListener('aia:result-updated', updated)
    return () => window.removeEventListener('aia:result-updated', updated)
  }, [sessionId])
  const [isLoading, setIsLoading] = useState(enabled)

  useEffect(() => {
    if (!enabled) return
    const controller = new AbortController()
    queueMicrotask(() => {
      if (controller.signal.aborted) return
      setIsLoading(true)
      setError(null)
    })
    apiGet<ResultView>(`/api/runs/${encodeURIComponent(sessionId)}/result`, controller.signal)
      .then((result) => {
        if (controller.signal.aborted) return
        setSnapshot({ id: sessionId, value: result })
        setIsLoading(false)
      })
      .catch((err) => {
        if (controller.signal.aborted) return
        setError(err instanceof Error ? err.message : String(err))
        setIsLoading(false)
      })
    return () => controller.abort()
  }, [sessionId, enabled, reloadToken])

  const data = enabled && snapshot?.id === sessionId ? snapshot.value : null
  return { data, error, isLoading: enabled && (isLoading || !data && !error) }
}
