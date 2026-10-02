import { usePreflight } from './usePreflight'
import { useRunStatus } from './useRunStatus'
import { useResult } from './useResult'
import { useShellStore } from '../state/shellStore'
import { guardianStatus } from '../api/guardianStatus'
export type { GuardianState, GuardianStatus } from '../api/guardianStatus'

export function useGuardianState() {
  const { activeRunId, codexActivity } = useShellStore()
  const { data: preflight } = usePreflight()
  const { data: status, error } = useRunStatus(activeRunId)
  const ended = ['COMPLETED', 'ABORTED', 'FAILED'].includes(status?.session?.status ?? '')
  const { data: result } = useResult(activeRunId ?? '', { enabled: Boolean(activeRunId) && ended })
  return guardianStatus({ ready: preflight?.readiness_code === 'READY', selected: Boolean(activeRunId), status, result,
    error: Boolean(error), approval: codexActivity?.runId === activeRunId && Boolean(codexActivity?.terminalAction) })
}
