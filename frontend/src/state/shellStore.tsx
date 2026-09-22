import { createContext, useCallback, useContext, useEffect, useMemo, useReducer, type ReactNode } from 'react'

export type ShellView = 'dashboard' | 'terminal' | 'policy' | 'history' | 'results'

/** Live signal reported by TerminalPane's useTerminalSession instance so
 * GuardianHero (mounted in the dashboard view, a sibling -- not an
 * ancestor -- of TerminalPane) can reflect Codex's current activity
 * without lifting the whole terminal hook (which is tightly coupled to a
 * DOM ref) out of TerminalPane. */
export interface TerminalActivitySignal {
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

interface ShellState {
  activeView: ShellView
  sidebarCollapsed: boolean
  rightPanelCollapsed: boolean
  settingsModalOpen: boolean
  /** The single protected run currently shown in the center pane -- the
   * shell shows one active run at a time (not a multi-tab workspace);
   * browsing other runs happens via the history/results lists, which
   * replace the active run when clicked. Persisted so a reload re-attaches
   * to the same run instead of losing context. */
  activeRunId: string | null
  terminalActivity: TerminalActivitySignal | null
}

type ShellAction =
  | { type: 'SET_VIEW'; view: ShellView }
  | { type: 'TOGGLE_SIDEBAR' }
  | { type: 'TOGGLE_RIGHT_PANEL' }
  | { type: 'OPEN_SETTINGS_MODAL' }
  | { type: 'CLOSE_SETTINGS_MODAL' }
  | { type: 'SET_ACTIVE_RUN'; id: string }
  | { type: 'CLEAR_ACTIVE_RUN' }
  | { type: 'SET_TERMINAL_ACTIVITY'; signal: TerminalActivitySignal }
  | { type: 'CLEAR_TERMINAL_ACTIVITY'; runId: string }

function initialState(): ShellState {
  return {
    activeView: 'dashboard',
    sidebarCollapsed: false,
    rightPanelCollapsed: false,
    settingsModalOpen: false,
    activeRunId: readStoredActiveRunId(),
    terminalActivity: null,
  }
}

function reducer(state: ShellState, action: ShellAction): ShellState {
  switch (action.type) {
    case 'SET_VIEW':
      return { ...state, activeView: action.view }
    case 'TOGGLE_SIDEBAR':
      return { ...state, sidebarCollapsed: !state.sidebarCollapsed }
    case 'TOGGLE_RIGHT_PANEL':
      return { ...state, rightPanelCollapsed: !state.rightPanelCollapsed }
    case 'OPEN_SETTINGS_MODAL':
      return { ...state, settingsModalOpen: true }
    case 'CLOSE_SETTINGS_MODAL':
      return { ...state, settingsModalOpen: false }
    case 'SET_ACTIVE_RUN':
      return { ...state, activeRunId: action.id }
    case 'CLEAR_ACTIVE_RUN':
      return { ...state, activeRunId: null }
    case 'SET_TERMINAL_ACTIVITY':
      return { ...state, terminalActivity: action.signal }
    case 'CLEAR_TERMINAL_ACTIVITY':
      return state.terminalActivity?.runId === action.runId ? { ...state, terminalActivity: null } : state
    default:
      return state
  }
}

interface ShellContextValue extends ShellState {
  setView: (view: ShellView) => void
  toggleSidebar: () => void
  toggleRightPanel: () => void
  openSettingsModal: () => void
  closeSettingsModal: () => void
  setActiveRun: (id: string) => void
  clearActiveRun: () => void
  reportTerminalActivity: (signal: TerminalActivitySignal) => void
  clearTerminalActivity: (runId: string) => void
}

const ShellContext = createContext<ShellContextValue | null>(null)

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
  const toggleSidebar = useCallback(() => dispatch({ type: 'TOGGLE_SIDEBAR' }), [])
  const toggleRightPanel = useCallback(() => dispatch({ type: 'TOGGLE_RIGHT_PANEL' }), [])
  const openSettingsModal = useCallback(() => dispatch({ type: 'OPEN_SETTINGS_MODAL' }), [])
  const closeSettingsModal = useCallback(() => dispatch({ type: 'CLOSE_SETTINGS_MODAL' }), [])
  const setActiveRun = useCallback((id: string) => dispatch({ type: 'SET_ACTIVE_RUN', id }), [])
  const clearActiveRun = useCallback(() => dispatch({ type: 'CLEAR_ACTIVE_RUN' }), [])
  const reportTerminalActivity = useCallback((signal: TerminalActivitySignal) => dispatch({ type: 'SET_TERMINAL_ACTIVITY', signal }), [])
  const clearTerminalActivity = useCallback((runId: string) => dispatch({ type: 'CLEAR_TERMINAL_ACTIVITY', runId }), [])

  const value = useMemo<ShellContextValue>(
    () => ({
      ...state,
      setView,
      toggleSidebar,
      toggleRightPanel,
      openSettingsModal,
      closeSettingsModal,
      setActiveRun,
      clearActiveRun,
      reportTerminalActivity,
      clearTerminalActivity,
    }),
    [
      state,
      setView,
      toggleSidebar,
      toggleRightPanel,
      openSettingsModal,
      closeSettingsModal,
      setActiveRun,
      clearActiveRun,
      reportTerminalActivity,
      clearTerminalActivity,
    ],
  )

  return <ShellContext.Provider value={value}>{children}</ShellContext.Provider>
}

export function useShellStore(): ShellContextValue {
  const ctx = useContext(ShellContext)
  if (!ctx) {
    throw new Error('useShellStore must be used within ShellStoreProvider')
  }
  return ctx
}
