import { createContext, useContext } from 'react'

/** The five rail destinations (EPIC-020). Result and restore live inside history; new run is a sheet. */
export type ShellView = 'home' | 'work' | 'policy' | 'history' | 'settings'

/** Live Codex status shared with the home view's guardian. */
export interface CodexActivitySignal {
  runId: string
  mode: string
  terminalAction: string | null
}

const ACTIVE_RUN_STORAGE_KEY = 'aia.activeRunId'

function readStoredActiveRunId(): string | null {
  try {
    return window.localStorage.getItem(ACTIVE_RUN_STORAGE_KEY)
  } catch {
    return null
  }
}

export interface ShellState {
  activeView: ShellView
  /** New protected run sheet (④). */
  newRunOpen: boolean
  /** The single protected run the work and history views show. Persisted so
   * a reload re-attaches to the same run instead of losing context. */
  activeRunId: string | null
  codexActivity: CodexActivitySignal | null
  /** Run whose result the history view shows; null shows the list. */
  historyRunId: string | null
  /** Bumped to ask the work view to open its end-session confirmation. */
  endRequest: number
}

export type ShellAction =
  | { type: 'SET_VIEW'; view: ShellView }
  | { type: 'OPEN_NEW_RUN' }
  | { type: 'CLOSE_NEW_RUN' }
  | { type: 'SET_ACTIVE_RUN'; id: string }
  | { type: 'CLEAR_ACTIVE_RUN' }
  | { type: 'SET_CODEX_ACTIVITY'; signal: CodexActivitySignal }
  | { type: 'CLEAR_CODEX_ACTIVITY'; runId: string }
  | { type: 'REQUEST_END' }
  | { type: 'OPEN_RESULT'; id: string }
  | { type: 'CLOSE_RESULT' }

export function initialState(): ShellState {
  return {
    activeView: 'home',
    newRunOpen: false,
    activeRunId: readStoredActiveRunId(),
    codexActivity: null,
    historyRunId: null,
    endRequest: 0,
  }
}

export function reducer(state: ShellState, action: ShellAction): ShellState {
  switch (action.type) {
    case 'SET_VIEW':
      // Entering history from the rail always starts at the list.
      return { ...state, activeView: action.view, historyRunId: action.view === 'history' ? null : state.historyRunId }
    case 'OPEN_NEW_RUN':
      return { ...state, newRunOpen: true }
    case 'CLOSE_NEW_RUN':
      return { ...state, newRunOpen: false }
    case 'SET_ACTIVE_RUN':
      return { ...state, activeRunId: action.id }
    case 'CLEAR_ACTIVE_RUN':
      return { ...state, activeRunId: null }
    case 'SET_CODEX_ACTIVITY':
      return { ...state, codexActivity: action.signal }
    case 'CLEAR_CODEX_ACTIVITY':
      return state.codexActivity?.runId === action.runId ? { ...state, codexActivity: null } : state
    case 'REQUEST_END':
      return { ...state, activeView: 'work', endRequest: state.endRequest + 1 }
    case 'OPEN_RESULT':
      return { ...state, activeView: 'history', activeRunId: action.id, historyRunId: action.id }
    case 'CLOSE_RESULT':
      return { ...state, historyRunId: null }
    default:
      return state
  }
}

export interface ShellContextValue extends ShellState {
  setView: (view: ShellView) => void
  openNewRun: () => void
  closeNewRun: () => void
  setActiveRun: (id: string) => void
  clearActiveRun: () => void
  reportCodexActivity: (signal: CodexActivitySignal) => void
  clearCodexActivity: (runId: string) => void
  requestEnd: () => void
  /** Show one run's result (③) in the history view and select it. */
  openResult: (id: string) => void
  closeResult: () => void
}

export const ShellContext = createContext<ShellContextValue | null>(null)

export function useShellStore(): ShellContextValue {
  const ctx = useContext(ShellContext)
  if (!ctx) {
    throw new Error('useShellStore must be used within ShellStoreProvider')
  }
  return ctx
}
