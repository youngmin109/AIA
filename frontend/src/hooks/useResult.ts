import { useEffect, useState } from 'react'
import { apiGet } from '../api/client'
import type { ResultView } from '../api/resultTypes'

/** One-shot fetch (not polled -- a completed run's result is static). */
export function useResult(sessionId: string) {
  const [data, setData] = useState<ResultView | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(true)

  useEffect(() => {
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
  }, [sessionId])

  return { data, error, isLoading }
}
