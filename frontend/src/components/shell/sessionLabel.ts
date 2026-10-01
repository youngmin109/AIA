/**
 * A session UUID is an internal correlation key, not a useful name for a
 * person.  The UI therefore uses the agent and Workspace as the visible
 * session label.  The UUID stays in the API and audit evidence unchanged.
 */
export function workspaceShortName(workspace?: string | null): string {
  if (!workspace) return '새 작업공간'

  const parts = workspace.replace(/[\\/]+$/, '').split(/[\\/]/).filter(Boolean)
  return parts.at(-1) || workspace
}

export function sessionDisplayName(workspace?: string | null): string {
  return `Codex · ${workspaceShortName(workspace)}`
}
