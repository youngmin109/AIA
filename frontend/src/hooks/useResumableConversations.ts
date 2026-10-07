import { useEffect, useState } from 'react'
import { codexConversations, type ResumableConversation } from '../api/endpoints'

/** AIA-opened Codex conversations, loaded when the resume choice is shown; null while loading. */
export function useResumableConversations(enabled: boolean): ResumableConversation[] | null {
  const [conversations, setConversations] = useState<ResumableConversation[] | null>(null)
  useEffect(() => {
    if (!enabled) return
    let cancelled = false
    codexConversations()
      .then(result => { if (!cancelled) setConversations(result.conversations ?? []) })
      .catch(() => { if (!cancelled) setConversations([]) })
    return () => { cancelled = true }
  }, [enabled])
  return conversations
}
