import { useCallback } from 'react'
import { apiGet } from '../api/client'
import { usePolling } from './usePolling'

export interface RunAction {
  action_id?: string
  enforcement_decision?: string
  policy_decision?: string
  operation?: string
  observed_at?: string
  [key: string]: unknown
}

/** Live actions of a run (latest_actions in the status is capped at 20). */
export function useRunActions(runId: string | null, enabled: boolean) {
  const fetchFn = useCallback(
    (signal: AbortSignal) => apiGet<{ actions?: RunAction[] }>(`/api/runs/${encodeURIComponent(runId ?? '')}/actions`, signal).then(body => body.actions ?? []),
    [runId],
  )
  return usePolling<RunAction[]>(fetchFn, { intervalMs: 2_000, enabled: Boolean(runId) && enabled, resetKey: runId })
}

/** A CONTAIN decision is a block decision; it is not proof that execution was blocked. */
export function blockDecisionCount(actions: RunAction[] | null | undefined): number {
  return (actions ?? []).filter(action => action.enforcement_decision === 'CONTAIN').length
}
