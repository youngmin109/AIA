import { useEffect, useRef } from 'react'
import { useShellStore } from '../state/shellStore'
import { useRunList, isRunActive } from './useRunList'

/**
 * Runs once, the first time the run list resolves after mount: drops a
 * stored activeRunId if that run no longer exists at all, and auto-adopts
 * the single RUNNING run if nothing was stored. Intentionally does not
 * re-run on every subsequent poll -- otherwise closing the active run pane
 * while exactly one run is still RUNNING would immediately re-open it.
 */
export function useActiveRunReconciliation() {
  const { activeRunId, setActiveRun, clearActiveRun } = useShellStore()
  const { data: runs } = useRunList()
  const reconciledRef = useRef(false)

  useEffect(() => {
    if (!runs || reconciledRef.current) return
    reconciledRef.current = true

    if (activeRunId) {
      const stillExists = runs.some((run) => run.session_id === activeRunId)
      if (!stillExists) clearActiveRun()
      return
    }

    const running = runs.filter(isRunActive)
    if (running.length === 1) setActiveRun(running[0].session_id)
  }, [runs, activeRunId, setActiveRun, clearActiveRun])
}
