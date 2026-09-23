/** Narrow interface for the local Windows WebView bridge.
 *
 * The browser preview intentionally has no filesystem-picker permission.
 * In that case callers keep the manual path input available instead of
 * pretending a browser dialog is equivalent to the native folder picker.
 */
type WorkspacePicker = {
  choose_workspace?: () => Promise<{ path?: string | null }>
}

declare global {
  interface Window {
    pywebview?: { api?: WorkspacePicker }
  }
}

export function hasNativeWorkspacePicker(): boolean {
  return typeof window.pywebview?.api?.choose_workspace === 'function'
}

export async function chooseNativeWorkspace(): Promise<string | null> {
  const pick = window.pywebview?.api?.choose_workspace
  if (!pick) return null
  const result = await pick()
  return typeof result?.path === 'string' && result.path.trim() ? result.path : null
}
