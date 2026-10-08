import { useCallback, useEffect, useState } from 'react'
import { codexConnectors } from '../api/endpoints'
import type { CodexConnector } from '../api/connectorView'

/** Connectors of an open conversation; null while loading or when the conversation is not open yet. */
export function useCodexConnectors(runId: string, enabled: boolean) {
  const [connectors, setConnectors] = useState<CodexConnector[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [reloadToken, setReloadToken] = useState(0)
  const reload = useCallback(() => setReloadToken(value => value + 1), [])
  useEffect(() => {
    if (!enabled) return
    let cancelled = false
    codexConnectors(runId)
      .then(result => { if (!cancelled) { setConnectors(result.connectors ?? []); setError(null) } })
      .catch(failure => { if (!cancelled) setError(failure instanceof Error ? failure.message : String(failure)) })
    return () => { cancelled = true }
  }, [runId, enabled, reloadToken])
  return { connectors, error, reload }
}
