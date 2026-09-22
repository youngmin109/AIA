import { useCallback } from 'react'
import { apiGet } from '../api/client'
import type { RunSummary } from '../api/types'
import { usePolling } from './usePolling'

/** Mirrors dashboard.html's adaptive cadence: faster while a tab is open
 * (a run may be actively transitioning), slower otherwise. */
export function useRunList({ activeTabCount = 0 }: { activeTabCount?: number } = {}) {
  const fetchFn = useCallback(
    (signal: AbortSignal) => apiGet<{ runs: RunSummary[] }>('/api/runs', signal).then((body) => body.runs ?? []),
    [],
  )
  return usePolling<RunSummary[]>(fetchFn, { intervalMs: activeTabCount > 0 ? 5_000 : 15_000 })
}

const RUNNING_STATUSES = new Set(['RUNNING', 'CREATED', 'PROTECTING', 'STARTING'])

export function isRunActive(run: RunSummary): boolean {
  return RUNNING_STATUSES.has(String(run.status))
}
