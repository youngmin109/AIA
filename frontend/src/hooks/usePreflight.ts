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

let inflight: Promise<Preflight> | null = null
let cached: Preflight | null = null
let cachedAt = 0

async function loadPreflight(): Promise<Preflight> {
  if (cached && Date.now() - cachedAt < 1_000) return cached
  if (!inflight) {
    inflight = apiGet<Preflight>('/api/preflight')
      .then((value) => { cached = value; cachedAt = Date.now(); return value })
      .finally(() => { inflight = null })
  }
  return inflight
}

/**
 * Same cadence dashboard.html already proved out for readiness cards.
 * Callers waiting on a specific transition (e.g. the Hook setup flow
 * watching for the user to finish trusting the Hook in Codex) can pass a
 * shorter interval; usePolling's effect already re-runs when intervalMs
 * changes, so this can be computed dynamically from the previous poll's
 * own result.
 */
export function usePreflight(intervalMs = 30_000, enabled = true) {
  // Multiple panels need the same readiness state. Share the request so the
  // local server does not queue identical preflight work at startup.
  const fetchFn = useCallback((_signal: AbortSignal) => loadPreflight(), [])
  return usePolling<Preflight>(fetchFn, { intervalMs, enabled })
}
