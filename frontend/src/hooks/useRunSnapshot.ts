import { useEffect, useState } from 'react'
import { apiGet } from '../api/client'
import type { RunStatus } from '../api/types'

/** One read of a finished run's status (for its observed file activity); reloads after a restore. */
export function useRunSnapshot(runId: string): RunStatus | null {
  const [snapshot, setSnapshot] = useState<{ id: string; data: RunStatus } | null>(null)
  const [token, setToken] = useState(0)
  useEffect(() => {
    const reload = () => setToken(value => value + 1)
    window.addEventListener('aia:result-updated', reload)
    return () => window.removeEventListener('aia:result-updated', reload)
  }, [])
  useEffect(() => {
    const controller = new AbortController()
    apiGet<RunStatus>(`/api/runs/${encodeURIComponent(runId)}`, controller.signal)
      .then(data => { if (!controller.signal.aborted) setSnapshot({ id: runId, data }) })
      .catch(() => { /* the file breakdown is optional; the result itself still renders */ })
    return () => controller.abort()
  }, [runId, token])
  return snapshot?.id === runId ? snapshot.data : null
}
