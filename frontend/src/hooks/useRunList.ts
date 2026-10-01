import { createContext, createElement, useCallback, useContext, type ReactNode } from 'react'
import { apiGet } from '../api/client'
import type { RunSummary } from '../api/types'
import { usePolling, type UsePollingResult } from './usePolling'
import { useShellStore } from '../state/shellStore'

const RunListContext = createContext<UsePollingResult<RunSummary[]> | null>(null)

/** Mirrors dashboard.html's adaptive cadence: faster while a run is active
 * (it may be transitioning), slower otherwise. */
function usePolledRunList({ hasActiveRun = false }: { hasActiveRun?: boolean } = {}) {
  const fetchFn = useCallback(
    (signal: AbortSignal) => apiGet<{ runs: RunSummary[] }>('/api/runs', signal).then((body) => body.runs ?? []),
    [],
  )
  return usePolling<RunSummary[]>(fetchFn, { intervalMs: hasActiveRun ? 5_000 : 15_000 })
}

/**
 * `/api/runs` verifies completed Result Bundles while it builds a list.
 * Keep one poller at the application boundary and share its snapshot with
 * the sidebar, status bar, audit list, and reconciliation logic.
 */
export function RunListProvider({ children }: { children: ReactNode }) {
  const { activeRunId } = useShellStore()
  const value = usePolledRunList({ hasActiveRun: Boolean(activeRunId) })
  return createElement(RunListContext.Provider, { value }, children)
}

export function useRunList(): UsePollingResult<RunSummary[]> {
  const value = useContext(RunListContext)
  if (!value) throw new Error('useRunList must be used within RunListProvider')
  return value
}

const RUNNING_STATUSES = new Set(['RUNNING', 'CREATED', 'PROTECTING', 'STARTING'])

export function isRunActive(run: RunSummary): boolean {
  // A run whose AIA coordinator is gone keeps its last RUNNING snapshot on
  // purpose (evidence is preserved), but nothing is running any more: it
  // must not count as active or be auto-opened as the current run.
  const reconciliation = run.runtime_reconciliation as { orphaned?: boolean } | undefined
  if (reconciliation?.orphaned) return false
  return RUNNING_STATUSES.has(String(run.status))
}
