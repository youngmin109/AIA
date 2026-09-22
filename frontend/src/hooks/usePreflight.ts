import { useCallback } from 'react'
import { apiGet } from '../api/client'
import { usePolling } from './usePolling'

export interface PreflightCheck {
  name: string
  label: string
  ok: boolean
  detail?: string
  optional?: boolean
  stale?: boolean
}

export interface Preflight {
  ready?: boolean
  readiness_code?: string
  next_step?: string
  checks?: PreflightCheck[]
  hook_trust?: { status?: string; detail?: string }
  hook_activation?: { status?: string; detail?: string }
  codex_hook_trust?: { available?: boolean; hooks?: Array<{ event?: string; trust_status?: string }> }
}

/** Same cadence dashboard.html already proved out for readiness cards. */
export function usePreflight() {
  const fetchFn = useCallback((signal: AbortSignal) => apiGet<Preflight>('/api/preflight', signal), [])
  return usePolling<Preflight>(fetchFn, { intervalMs: 30_000 })
}
