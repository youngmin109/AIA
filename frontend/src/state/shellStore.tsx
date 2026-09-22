import { createContext, useCallback, useContext, useEffect, useMemo, useReducer, type ReactNode } from 'react'

export type ShellView = 'dashboard' | 'history' | 'results'

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
}

type ShellAction =
  | { type: 'SET_VIEW'; view: ShellView }
  | { type: 'TOGGLE_SIDEBAR' }
  | { type: 'TOGGLE_RIGHT_PANEL' }
  | { type: 'OPEN_SETTINGS_MODAL' }
  | { type: 'CLOSE_SETTINGS_MODAL' }
  | { type: 'SET_ACTIVE_RUN'; id: string }
  | { type: 'CLEAR_ACTIVE_RUN' }

function initialState(): ShellState {
  return {
    activeView: 'dashboard',
    sidebarCollapsed: false,
    rightPanelCollapsed: false,
    settingsModalOpen: false,
    activeRunId: readStoredActiveRunId(),
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
    }),
    [state, setView, toggleSidebar, toggleRightPanel, openSettingsModal, closeSettingsModal, setActiveRun, clearActiveRun],
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
