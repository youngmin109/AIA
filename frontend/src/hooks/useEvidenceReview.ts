import { useEffect, useState } from 'react'
import { useRunStatus } from './useRunStatus'
import { isSessionRunning } from '../api/display'
import { queueUiPreferenceWrite, UI_PREFERENCE_RESTORED_EVENT } from '../api/preferenceSync'
import { ackKeys, latestAcked, pendingReviews, type AckedMap, type AckMark } from '../api/evidenceReview'

const STORAGE_KEY = 'aia.ackedIncidents'

export type { AckMark }

function readAcked(): AckedMap {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    const parsed = raw ? JSON.parse(raw) as AckedMap : {}
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed)
      ? latestAcked(parsed)
      : {}
  } catch {
    return {}
  }
}

function writeAcked(value: AckedMap): AckedMap {
  const latest = latestAcked(value)
  const serialized = JSON.stringify(latest)
  try {
    window.localStorage.setItem(STORAGE_KEY, serialized)
  } catch {
    // Per-viewer convenience only; ignore storage failures (private mode, etc).
  }
  queueUiPreferenceWrite(STORAGE_KEY, serialized)
  return latest
}

/** Surfaces the oldest not-yet-acknowledged flagged event of a RUNNING run,
 * one at a time, so EvidenceReviewModal can prompt the user to mark it
 * reviewed. `remaining` counts how many are waiting (this one included) and
 * `ackAll` clears them in one step. Purely a local read/annotate layer over data
 * useRunStatus already polls -- it never blocks or alters execution. */
export function useEvidenceReview(runId: string | null) {
  const { data: status } = useRunStatus(runId, { enabled: Boolean(runId) })
  const [acked, setAcked] = useState<AckedMap>(() => readAcked())

  useEffect(() => {
    let current = true
    queueMicrotask(() => {
      if (current) setAcked(readAcked())
    })
    return () => {
      current = false
    }
  }, [runId])

  useEffect(() => {
    const restoreAcked = (event: Event) => {
      if ((event as CustomEvent<string>).detail === STORAGE_KEY) setAcked(readAcked())
    }
    window.addEventListener(UI_PREFERENCE_RESTORED_EVENT, restoreAcked)
    return () => window.removeEventListener(UI_PREFERENCE_RESTORED_EVENT, restoreAcked)
  }, [])

  const events = status?.events ?? []
  const live = status ? isSessionRunning(status.session?.status, status.runtime_reconciliation?.orphaned) : false
  const waiting = pendingReviews(runId, events, acked, live)
  const pending = waiting.length ? events[waiting[0].index] : null

  function ack(mark: AckMark) {
    if (!waiting.length) return
    setAcked(writeAcked(ackKeys(acked, [waiting[0].key], mark)))
  }

  function ackAll(mark: AckMark = 'reviewed') {
    if (!waiting.length) return
    setAcked(writeAcked(ackKeys(acked, waiting.map(item => item.key), mark)))
  }

  return { pending, remaining: waiting.length, ack, ackAll }
}
