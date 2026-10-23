import type { SecurityEvent } from './types'

export type AckMark = 'problem' | 'reviewed'
export type AckedMap = Record<string, AckMark>

export interface PendingReview {
  index: number
  key: string
}

const MAX_ENTRIES = 500
const MAX_BYTES = 8 * 1024

// severity/category (set server-side, see presenters_result_events.py's
// safe_event_views) are what actually flag a policy-relevant event --
// decision/display_decision carry an enforcement-decision-first vocabulary
// (CONTAIN/REFUSE/BLOCKED/TERMINATED, or OBSERVED for sensors that don't
// evaluate policy), not a plain VIOLATION/INDETERMINATE string. SENSOR-category
// pseudo-events (Hook/File/Process health blips) are excluded -- they aren't
// policy decisions.
export function isFlagged(event: SecurityEvent): boolean {
  return event.category !== 'SENSOR' && event.severity !== undefined && event.severity !== 'INFO'
}

export function eventKey(runId: string, event: SecurityEvent, index: number): string {
  return `${runId}:${event.event_id ?? event.chain_action_id ?? `idx${index}`}`
}

/** Keeps the newest entries and stays small enough for one stored preference. */
export function latestAcked(value: AckedMap): AckedMap {
  let entries = Object.entries(value).slice(-MAX_ENTRIES)
  while (entries.length) {
    const latest = Object.fromEntries(entries) as AckedMap
    if (new TextEncoder().encode(JSON.stringify(latest)).byteLength <= MAX_BYTES) return latest
    entries = entries.slice(1)
  }
  return {}
}

/**
 * Flagged events of the run that nobody has marked yet, oldest first.
 *
 * Only a run that is still running prompts. The status poll re-attaches to the
 * last run on every launch (aia.activeRunId), and a finished run's timeline can
 * hold up to 50 flagged events; prompting for those would put a wall of dialogs
 * over the start screen. Everything stays reviewable in the run's record.
 */
export function pendingReviews(runId: string | null, events: readonly SecurityEvent[], acked: AckedMap, live: boolean): PendingReview[] {
  if (!runId || !live) return []
  const pending: PendingReview[] = []
  events.forEach((event, index) => {
    if (!isFlagged(event)) return
    const key = eventKey(runId, event, index)
    if (!(key in acked)) pending.push({ index, key })
  })
  return pending
}

/** Records one mark for several events at once (the newest write wins). */
export function ackKeys(acked: AckedMap, keys: readonly string[], mark: AckMark): AckedMap {
  const next = { ...acked }
  for (const key of keys) {
    delete next[key]
    next[key] = mark
  }
  return latestAcked(next)
}
