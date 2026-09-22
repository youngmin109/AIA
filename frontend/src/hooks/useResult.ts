import { useEffect, useState } from 'react'
import { apiGet } from '../api/client'
import type { ResultView } from '../api/resultTypes'

/** One-shot fetch (not polled -- a completed run's result is static).
 * Pass `enabled: false` to skip fetching, e.g. while a run is still active
 * and /result would just report it unavailable. */
export function useResult(sessionId: string, { enabled = true }: { enabled?: boolean } = {}) {
  const [data, setData] = useState<ResultView | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(enabled)

  useEffect(() => {
    if (!enabled) {
      setIsLoading(false)
      return
    }
    const controller = new AbortController()
    setIsLoading(true)
    setError(null)
    apiGet<ResultView>(`/api/runs/${encodeURIComponent(sessionId)}/result`, controller.signal)
      .then((result) => {
        setData(result)
        setIsLoading(false)
      })
      .catch((err) => {
        if (controller.signal.aborted) return
        setError(err instanceof Error ? err.message : String(err))
        setIsLoading(false)
      })
    return () => controller.abort()
  }, [sessionId, enabled])

  return { data, error, isLoading }
}
