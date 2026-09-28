import { useCallback } from 'react'
import { apiGet } from '../api/client'
import type { RunSummary } from '../api/types'
import { usePolling } from './usePolling'

/** Mirrors dashboard.html's adaptive cadence: faster while a run is active
 * (it may be transitioning), slower otherwise. */
export function useRunList({ hasActiveRun = false }: { hasActiveRun?: boolean } = {}) {
  const fetchFn = useCallback(
    (signal: AbortSignal) => apiGet<{ runs: RunSummary[] }>('/api/runs', signal).then((body) => body.runs ?? []),
    [],
  )
  return usePolling<RunSummary[]>(fetchFn, { intervalMs: hasActiveRun ? 5_000 : 15_000 })
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
