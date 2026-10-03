import { useCallback, useEffect, useRef, useState } from 'react'
import { nextConnectionFailures, pollOutcomeOf } from '../api/connectionState'

interface UsePollingOptions {
  intervalMs: number
  enabled?: boolean
  resetKey?: string | null
}

export interface UsePollingResult<T> {
  data: T | null
  error: Error | null
  isLoading: boolean
  updatedAt?: number | null
  /** Consecutive polls that got no response from the local server. */
  connectionFailures?: number
  refetch: () => void
}

/**
 * Polls `fetchFn` on a fixed interval, pausing while the tab/window is
 * hidden (the desktop shell's WebView still fires visibilitychange) and
 * while `enabled` is false. Mirrors the cadence the old Jinja pages already
 * proved out (dashboard.html: 30s preflight / 5-15s run list, workbench.html:
 * 1s run status) rather than reaching for a caching library.
 */
export function usePolling<T>(fetchFn: (signal: AbortSignal) => Promise<T>, { intervalMs, enabled = true, resetKey = 'default' }: UsePollingOptions): UsePollingResult<T> {
  const [snapshot, setSnapshot] = useState<{ key: string | null; data: T; updatedAt: number } | null>(null)
  const [failure, setFailure] = useState<{ key: string | null; error: Error } | null>(null)
  const error = failure?.key === resetKey ? failure.error : null
  const [isLoading, setIsLoading] = useState(true)
  const [connectionFailures, setConnectionFailures] = useState(0)
  const fetchRef = useRef(fetchFn)
  fetchRef.current = fetchFn

  const tick = useCallback(async (signal: AbortSignal) => {
    try {
      const next = await fetchRef.current(signal)
      if (!signal.aborted) {
        setSnapshot({ key: resetKey, data: next, updatedAt: Date.now() })
        setFailure(null)
        setConnectionFailures(0)
        setIsLoading(false)
      }
    } catch (err) {
      if (!signal.aborted) {
        setFailure({ key: resetKey, error: err instanceof Error ? err : new Error(String(err)) })
        setConnectionFailures(previous => nextConnectionFailures(previous, pollOutcomeOf(err)))
        setIsLoading(false)
      }
    }
  }, [resetKey])

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
    let inFlight = false

    const runTick = () => {
      if (stopped) return
      if (inFlight) return
      if (document.hidden) {
        timer = setTimeout(runTick, intervalMs)
        return
      }
      inFlight = true
      controller = new AbortController()
      tick(controller.signal).finally(() => {
        inFlight = false
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

  const current = snapshot?.key === resetKey ? snapshot : null
  return { data: current?.data ?? null, error, isLoading: enabled && !current ? !error : isLoading, updatedAt: current?.updatedAt ?? null, connectionFailures, refetch }
}
