import { createContext, createElement, useCallback, useContext, useState, type ReactNode } from 'react'
import { isSessionRunning } from '../api/display'
import { apiGet } from '../api/client'
import type { RunStatus } from '../api/types'
import { usePolling, type UsePollingResult } from './usePolling'
import { useShellStore } from '../state/shellStore'

const Context = createContext<{ sessionId: string | null; value: UsePollingResult<RunStatus> } | null>(null)
export function RunStatusProvider({ children }: { children: ReactNode }) {
  const { activeRunId } = useShellStore()
  const [cadence, setCadence] = useState({ id: activeRunId, live: true })
  const fetchFn = useCallback(async (signal: AbortSignal) => {
    const status = await apiGet<RunStatus>(`/api/runs/${encodeURIComponent(activeRunId ?? '')}`, signal)
    if (!signal.aborted) {
      const live = isSessionRunning(status.session?.status, status.runtime_reconciliation?.orphaned)
      setCadence(previous => previous.id === activeRunId && previous.live === live ? previous : { id: activeRunId, live })
    }
    return status
  }, [activeRunId])
  const value = usePolling(fetchFn, { intervalMs: cadence.id === activeRunId && !cadence.live ? 10000 : 1000, enabled: Boolean(activeRunId), resetKey: activeRunId })
  return createElement(Context.Provider, { value: { sessionId: activeRunId, value } }, children)
}
/** One poller per selected session, shared by all views and the Guardian. */
export function useRunStatus(sessionId: string | null, { enabled = true }: { enabled?: boolean } = {}): UsePollingResult<RunStatus> {
  const shared = useContext(Context)
  if (!shared) throw new Error('useRunStatus must be used within RunStatusProvider')
  if (!enabled || !sessionId || sessionId !== shared.sessionId) return { data: null, error: null, isLoading: Boolean(enabled && sessionId), refetch: shared.value.refetch }
  return shared.value
}
