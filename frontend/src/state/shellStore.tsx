import { createContext, useContext } from 'react'

export type ShellView = 'dashboard' | 'terminal' | 'policy' | 'audit'

/** Live Codex status shared with GuardianHero in the dashboard view. */
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
  sidebarCollapsed: boolean
  rightPanelCollapsed: boolean
  settingsModalOpen: boolean
  /** The single protected run currently shown in the center pane -- the
   * shell shows one active run at a time (not a multi-tab workspace);
   * browsing other runs happens via the audit view's list, which replaces
   * the active run when clicked. Persisted so a reload re-attaches to the
   * same run instead of losing context. */
  activeRunId: string | null
  codexActivity: CodexActivitySignal | null
}

export type ShellAction =
  | { type: 'SET_VIEW'; view: ShellView }
  | { type: 'TOGGLE_SIDEBAR' }
  | { type: 'TOGGLE_RIGHT_PANEL' }
  | { type: 'OPEN_SETTINGS_MODAL' }
  | { type: 'CLOSE_SETTINGS_MODAL' }
  | { type: 'SET_ACTIVE_RUN'; id: string }
  | { type: 'CLEAR_ACTIVE_RUN' }
  | { type: 'SET_CODEX_ACTIVITY'; signal: CodexActivitySignal }
  | { type: 'CLEAR_CODEX_ACTIVITY'; runId: string }

export function initialState(): ShellState {
  return {
    activeView: 'dashboard',
    sidebarCollapsed: false,
    rightPanelCollapsed: false,
    settingsModalOpen: false,
    activeRunId: readStoredActiveRunId(),
    codexActivity: null,
  }
}

export function reducer(state: ShellState, action: ShellAction): ShellState {
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
    case 'SET_CODEX_ACTIVITY':
      return { ...state, codexActivity: action.signal }
    case 'CLEAR_CODEX_ACTIVITY':
      return state.codexActivity?.runId === action.runId ? { ...state, codexActivity: null } : state
    default:
      return state
  }
}

export interface ShellContextValue extends ShellState {
  setView: (view: ShellView) => void
  toggleSidebar: () => void
  toggleRightPanel: () => void
  openSettingsModal: () => void
  closeSettingsModal: () => void
  setActiveRun: (id: string) => void
  clearActiveRun: () => void
  reportCodexActivity: (signal: CodexActivitySignal) => void
  clearCodexActivity: (runId: string) => void
}

export const ShellContext = createContext<ShellContextValue | null>(null)

export function useShellStore(): ShellContextValue {
  const ctx = useContext(ShellContext)
  if (!ctx) {
    throw new Error('useShellStore must be used within ShellStoreProvider')
  }
  return ctx
}
