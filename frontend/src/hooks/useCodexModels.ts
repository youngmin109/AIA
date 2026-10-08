import { useEffect, useState } from 'react'
import { codexModels } from '../api/endpoints'
import type { CodexModel } from '../api/modelView'

/** Loads the model list once; an empty list hides the pickers (Codex then uses its default). */
export function useCodexModels(enabled = true): CodexModel[] {
  const [models, setModels] = useState<CodexModel[]>([])
  useEffect(() => {
    if (!enabled) return
    let cancelled = false
    codexModels()
      .then(result => { if (!cancelled) setModels(result.models ?? []) })
      .catch(() => { if (!cancelled) setModels([]) })
    return () => { cancelled = true }
  }, [enabled])
  return models
}
