import { useCallback, useEffect, useMemo, useReducer, type ReactNode } from 'react'
import { ShellContext, initialState, reducer, type CodexActivitySignal, type ShellContextValue, type ShellView } from './shellStore'

const ACTIVE_RUN_STORAGE_KEY = 'aia.activeRunId'

export function ShellStoreProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(reducer, undefined, initialState)

  useEffect(() => {
    try {
      if (state.activeRunId) window.localStorage.setItem(ACTIVE_RUN_STORAGE_KEY, state.activeRunId)
      else window.localStorage.removeItem(ACTIVE_RUN_STORAGE_KEY)
    } catch {
      // Per-viewer convenience only; ignore storage failures (private mode, etc).
    }
  }, [state.activeRunId])

  const setView = useCallback((view: ShellView) => dispatch({ type: 'SET_VIEW', view }), [])
  const openNewRun = useCallback(() => dispatch({ type: 'OPEN_NEW_RUN' }), [])
  const closeNewRun = useCallback(() => dispatch({ type: 'CLOSE_NEW_RUN' }), [])
  const setActiveRun = useCallback((id: string) => dispatch({ type: 'SET_ACTIVE_RUN', id }), [])
  const clearActiveRun = useCallback(() => dispatch({ type: 'CLEAR_ACTIVE_RUN' }), [])
  const reportCodexActivity = useCallback((signal: CodexActivitySignal) => dispatch({ type: 'SET_CODEX_ACTIVITY', signal }), [])
  const clearCodexActivity = useCallback((runId: string) => dispatch({ type: 'CLEAR_CODEX_ACTIVITY', runId }), [])
  const requestEnd = useCallback(() => dispatch({ type: 'REQUEST_END' }), [])

  const value = useMemo<ShellContextValue>(
    () => ({
      ...state,
      setView,
      openNewRun,
      closeNewRun,
      setActiveRun,
      clearActiveRun,
      reportCodexActivity,
      clearCodexActivity,
      requestEnd,
    }),
    [state, setView, openNewRun, closeNewRun, setActiveRun, clearActiveRun, reportCodexActivity, clearCodexActivity, requestEnd],
  )

  return <ShellContext.Provider value={value}>{children}</ShellContext.Provider>
}
