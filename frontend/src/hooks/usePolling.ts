import { useCallback, useEffect, useRef, useState } from 'react'

interface UsePollingOptions {
  intervalMs: number
  enabled?: boolean
}

interface UsePollingResult<T> {
  data: T | null
  error: Error | null
  isLoading: boolean
  refetch: () => void
}

/**
 * Polls `fetchFn` on a fixed interval, pausing while the tab/window is
 * hidden (the desktop shell's WebView still fires visibilitychange) and
 * while `enabled` is false. Mirrors the cadence the old Jinja pages already
 * proved out (dashboard.html: 30s preflight / 5-15s run list, workbench.html:
 * 1s run status) rather than reaching for a caching library.
 */
export function usePolling<T>(fetchFn: (signal: AbortSignal) => Promise<T>, { intervalMs, enabled = true }: UsePollingOptions): UsePollingResult<T> {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<Error | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const fetchRef = useRef(fetchFn)
  fetchRef.current = fetchFn

  const tick = useCallback(async (signal: AbortSignal) => {
    try {
      const next = await fetchRef.current(signal)
      if (!signal.aborted) {
        setData(next)
        setError(null)
        setIsLoading(false)
      }
    } catch (err) {
      if (!signal.aborted) {
        setError(err instanceof Error ? err : new Error(String(err)))
        setIsLoading(false)
      }
    }
  }, [])

  const [refetchToken, setRefetchToken] = useState(0)
  const refetch = useCallback(() => setRefetchToken((value) => value + 1), [])

  useEffect(() => {
    if (!enabled) {
      setIsLoading(false)
      return
    }
    let timer: ReturnType<typeof setTimeout> | null = null
    let controller: AbortController | null = null
    let stopped = false

    const runTick = () => {
      if (stopped || document.hidden) {
        timer = setTimeout(runTick, intervalMs)
        return
      }
      controller = new AbortController()
      tick(controller.signal).finally(() => {
        if (!stopped) timer = setTimeout(runTick, intervalMs)
      })
    }

    runTick()

    const onVisible = () => {
      if (!document.hidden && !stopped) {
        if (timer) clearTimeout(timer)
        runTick()
      }
    }
    document.addEventListener('visibilitychange', onVisible)

    return () => {
      stopped = true
      if (timer) clearTimeout(timer)
      controller?.abort()
      document.removeEventListener('visibilitychange', onVisible)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, intervalMs, tick, refetchToken])

  return { data, error, isLoading, refetch }
}
