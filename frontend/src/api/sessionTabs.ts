import type { RunSummary } from './types'
import { isHookVerificationRun, isRunActive } from './sessionNavigation.ts'

/** Conversations that can run at once; the server refuses more (one console worker each). */
export const MAX_SESSIONS = 4

export interface SessionTab {
  id: string
  /** Last folder name; parent/name when two open folders share it. */
  name: string
  path: string
  state: 'preparing' | 'running' | 'ended'
}

const PREPARING = new Set(['CREATED', 'PREPARING', 'PROTECTING', 'STARTING'])

function folderParts(workspace: string): string[] {
  return workspace.replace(/[\\/]+$/, '').split(/[\\/]/).filter(Boolean)
}

/**
 * One tab per live conversation, oldest first so tabs keep their place, plus
 * the shown run when it has ended (its result stays one click away).
 */
export function sessionTabs(runs: RunSummary[], activeRunId: string | null): SessionTab[] {
  const live = runs
    .filter(run => isRunActive(run) && !isHookVerificationRun(run))
    .sort((a, b) => (Date.parse(a.created_at ?? '') || 0) - (Date.parse(b.created_at ?? '') || 0))
  const shown = live.some(run => run.session_id === activeRunId) ? null : runs.find(run => run.session_id === activeRunId)
  const tabs = [...live, ...(shown ? [shown] : [])]
  const names = tabs.map(run => folderParts(String(run.workspace ?? '')))
  return tabs.map((run, index) => {
    const parts = names[index]
    const last = parts.at(-1) ?? '작업 폴더'
    const shared = names.filter(other => other.at(-1) === last).length > 1
    return {
      id: run.session_id,
      name: shared && parts.length > 1 ? `${parts.at(-2)}/${last}` : last,
      path: String(run.workspace ?? ''),
      state: run === shown ? 'ended' : PREPARING.has(run.status ?? '') ? 'preparing' : 'running',
    }
  })
}

/** A background conversation waiting for the user (approval, question, input or permission). */
export function needsAttention(status: Record<string, unknown> | null | undefined): boolean {
  return ['pending_approvals', 'pending_questions', 'pending_elicitations', 'pending_permissions']
    .some(key => {
      const pending = status?.[key]
      return Array.isArray(pending) && pending.length > 0
    })
}
