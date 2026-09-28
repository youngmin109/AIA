import { useEffect, useState } from 'react'
import { apiGet } from '../api/client'
import type { RecoveryStatusView } from '../api/resultTypes'

export function useRecoveryStatus(sessionId: string) {
  const [data, setData] = useState<RecoveryStatusView | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    apiGet<RecoveryStatusView>(`/api/runs/${encodeURIComponent(sessionId)}/recovery`, controller.signal)
      .then(setData)
      .catch(() => {
        if (!controller.signal.aborted) setData(null)
      })
    return () => controller.abort()
  }, [sessionId])

  return data
}
