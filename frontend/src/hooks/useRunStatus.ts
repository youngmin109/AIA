import { useCallback } from 'react'
import { apiGet } from '../api/client'
import type { RunStatus } from '../api/types'
import { usePolling } from './usePolling'

/**
 * Polls GET /api/runs/{session_id} every second while `enabled` — the same
 * cadence and endpoint workbench.html already used for the security panel
 * and terminal status. Callers should only enable this for the currently
 * focused run tab (see the shell store), not every open tab, to keep
 * backend load equivalent to the old one-page-at-a-time model.
 */
export function useRunStatus(sessionId: string | null, { enabled = true }: { enabled?: boolean } = {}) {
  const fetchFn = useCallback(
    (signal: AbortSignal) => {
      if (!sessionId) return Promise.reject(new Error('no session id'))
      return apiGet<RunStatus>(`/api/runs/${encodeURIComponent(sessionId)}`, signal)
    },
    [sessionId],
  )

  return usePolling<RunStatus>(fetchFn, { intervalMs: 1000, enabled: enabled && Boolean(sessionId) })
}
