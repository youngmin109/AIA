/** Narrow interface for the local Windows WebView bridge.
 *
 * The browser preview intentionally has no filesystem-picker permission.
 * In that case callers keep the manual path input available instead of
 * pretending a browser dialog is equivalent to the native folder picker.
 */
import { readPetSize } from './api/petSizePreference.ts'

type WorkspacePicker = {
  choose_workspace?: () => Promise<{ path?: string | null }>
  heartbeat?: () => Promise<boolean>
  set_title_bar?: (tint: string) => Promise<boolean>
  set_guardian_visible?: (visible: boolean) => Promise<boolean>
  set_guardian_size?: (size: number) => Promise<boolean>
  set_guardian_folded?: (folded: boolean) => Promise<boolean>
  open_main?: (view: string, sessionId: string | null) => Promise<boolean>
  open_guardian_help?: (topic: string) => Promise<boolean>
}

declare global {
  interface Window {
    pywebview?: { api?: WorkspacePicker }
  }
}

export function hasNativeWorkspacePicker(): boolean {
  return typeof window.pywebview?.api?.choose_workspace === 'function'
}

/** Colour the native Windows title bar like the page's colour theme. No-op in a browser. */
export function syncTitleBar(tint: string): void {
  window.pywebview?.api?.set_title_bar?.(tint).catch(() => {})
}

export async function chooseNativeWorkspace(): Promise<string | null> {
  const pick = window.pywebview?.api?.choose_workspace
  if (!pick) return null
  const result = await pick()
  return typeof result?.path === 'string' && result.path.trim() ? result.path : null
}

/**
 * Tell the desktop shell the page is alive while it is visible. When the
 * window is in front but these stop, the shell repaints and then reloads
 * the WebView (see aia_desktop/webview_recovery.py). No-op in a browser.
 */
export function startDesktopHeartbeat(intervalMs = 10_000): () => void {
  const beat = () => {
    if (document.hidden) return
    window.pywebview?.api?.heartbeat?.().catch(() => {})
  }
  const timer = window.setInterval(beat, intervalMs)
  document.addEventListener('visibilitychange', beat)
  window.addEventListener('pywebviewready', beat)
  return () => {
    window.clearInterval(timer)
    document.removeEventListener('visibilitychange', beat)
    window.removeEventListener('pywebviewready', beat)
  }
}

/** Native desktop pet is independent of main window minimize/restore. */
export function syncDesktopGuardian(): void {
  const show = window.pywebview?.api?.set_guardian_visible
  if (!show) return
  document.documentElement.dataset.nativeGuardian = 'on'
  let visible = true
  try { visible = localStorage.getItem('aia.pet') !== 'off' } catch { /* default on */ }
  const size = window.pywebview?.api?.set_guardian_size
  const prepared = size ? size(readPetSize()) : Promise.resolve(true)
  prepared.then(() => show(visible)).then(ok => { if (!ok) document.documentElement.dataset.nativeGuardian = 'off' })
    .catch(() => { document.documentElement.dataset.nativeGuardian = 'off' })
}
