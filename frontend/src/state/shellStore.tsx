import { createContext, useCallback, useContext, useMemo, useReducer, type ReactNode } from 'react'

export type ShellView = 'dashboard' | 'history' | 'results'

export interface RunTab {
  id: string
  title: string
  /** 'terminal' attaches the live Codex PTY; 'result' shows the static
   * result/incident view for a completed run. Defaults to 'terminal'. */
  kind?: 'terminal' | 'result'
}

interface ShellState {
  activeView: ShellView
  sidebarCollapsed: boolean
  rightPanelCollapsed: boolean
  settingsModalOpen: boolean
  openTabs: RunTab[]
  activeTabId: string | null
}

type ShellAction =
  | { type: 'SET_VIEW'; view: ShellView }
  | { type: 'TOGGLE_SIDEBAR' }
  | { type: 'TOGGLE_RIGHT_PANEL' }
  | { type: 'OPEN_SETTINGS_MODAL' }
  | { type: 'CLOSE_SETTINGS_MODAL' }
  | { type: 'OPEN_TAB'; tab: RunTab }
  | { type: 'CLOSE_TAB'; id: string }
  | { type: 'SET_ACTIVE_TAB'; id: string }

const initialState: ShellState = {
  activeView: 'dashboard',
  sidebarCollapsed: false,
  rightPanelCollapsed: false,
  settingsModalOpen: false,
  openTabs: [],
  activeTabId: null,
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
    case 'OPEN_TAB': {
      const exists = state.openTabs.some((tab) => tab.id === action.tab.id)
      const openTabs = exists ? state.openTabs : [...state.openTabs, action.tab]
      return { ...state, openTabs, activeTabId: action.tab.id }
    }
    case 'CLOSE_TAB': {
      const openTabs = state.openTabs.filter((tab) => tab.id !== action.id)
      const wasActive = state.activeTabId === action.id
      const activeTabId = wasActive
        ? (openTabs[openTabs.length - 1]?.id ?? null)
        : state.activeTabId
      return { ...state, openTabs, activeTabId }
    }
    case 'SET_ACTIVE_TAB':
      return { ...state, activeTabId: action.id }
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
  openTab: (tab: RunTab) => void
  closeTab: (id: string) => void
  setActiveTab: (id: string) => void
}

const ShellContext = createContext<ShellContextValue | null>(null)

export function ShellStoreProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(reducer, initialState)

  const setView = useCallback((view: ShellView) => dispatch({ type: 'SET_VIEW', view }), [])
  const toggleSidebar = useCallback(() => dispatch({ type: 'TOGGLE_SIDEBAR' }), [])
  const toggleRightPanel = useCallback(() => dispatch({ type: 'TOGGLE_RIGHT_PANEL' }), [])
  const openSettingsModal = useCallback(() => dispatch({ type: 'OPEN_SETTINGS_MODAL' }), [])
  const closeSettingsModal = useCallback(() => dispatch({ type: 'CLOSE_SETTINGS_MODAL' }), [])
  const openTab = useCallback((tab: RunTab) => dispatch({ type: 'OPEN_TAB', tab }), [])
  const closeTab = useCallback((id: string) => dispatch({ type: 'CLOSE_TAB', id }), [])
  const setActiveTab = useCallback((id: string) => dispatch({ type: 'SET_ACTIVE_TAB', id }), [])

  const value = useMemo<ShellContextValue>(
    () => ({
      ...state,
      setView,
      toggleSidebar,
      toggleRightPanel,
      openSettingsModal,
      closeSettingsModal,
      openTab,
      closeTab,
      setActiveTab,
    }),
    [state, setView, toggleSidebar, toggleRightPanel, openSettingsModal, closeSettingsModal, openTab, closeTab, setActiveTab],
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
