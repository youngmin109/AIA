import { useEffect, useState } from 'react'
import { useRunStatus } from './useRunStatus'
import type { SecurityEvent } from '../api/types'

const STORAGE_KEY = 'aia.ackedIncidents'

// severity/category (set server-side, see presenters.py's format_run_events)
// are what actually flag a policy-relevant event -- decision/display_decision
// carry an enforcement-decision-first vocabulary (CONTAIN/REFUSE/BLOCKED/
// TERMINATED, or OBSERVED for sensors that don't evaluate policy), not a
// plain VIOLATION/INDETERMINATE string. SENSOR-category pseudo-events (Hook/
// File/Process health blips) are excluded -- they aren't policy decisions.
function isFlagged(event: SecurityEvent): boolean {
  return event.category !== 'SENSOR' && event.severity !== undefined && event.severity !== 'INFO'
}

export type AckMark = 'problem' | 'reviewed'

function readAcked(): Record<string, AckMark> {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    return raw ? (JSON.parse(raw) as Record<string, AckMark>) : {}
  } catch {
    return {}
  }
}

function writeAcked(value: Record<string, AckMark>) {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(value))
  } catch {
    // Per-viewer convenience only; ignore storage failures (private mode, etc).
  }
}

function eventKey(runId: string, event: SecurityEvent, index: number): string {
  return `${runId}:${event.event_id ?? event.chain_action_id ?? `idx${index}`}`
}

/** Surfaces the oldest not-yet-acknowledged VIOLATION/INDETERMINATE event
 * for the active run, one at a time, so EvidenceReviewModal can prompt the
 * user to mark it reviewed. Purely a local read/annotate layer over data
 * useRunStatus already polls -- it never blocks or alters execution. */
export function useEvidenceReview(runId: string | null) {
  const { data: status } = useRunStatus(runId, { enabled: Boolean(runId) })
  const [acked, setAcked] = useState<Record<string, AckMark>>(() => readAcked())

  // Re-sync from storage when switching to a different run (a fresh mount
  // context), so a stale in-memory map from a prior run doesn't leak.
  useEffect(() => {
    setAcked(readAcked())
  }, [runId])

  const events = status?.events ?? []
  const pendingIndex = runId
    ? events.findIndex((event, index) => isFlagged(event) && !(eventKey(runId, event, index) in acked))
    : -1

  const pending = pendingIndex >= 0 ? events[pendingIndex] : null

  function ack(mark: AckMark) {
    if (!runId || pendingIndex < 0) return
    const key = eventKey(runId, events[pendingIndex], pendingIndex)
    const next = { ...acked, [key]: mark }
    writeAcked(next)
    setAcked(next)
  }

  return { pending, ack }
}
