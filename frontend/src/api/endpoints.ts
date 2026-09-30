import { apiGet, apiPost, apiPostTolerant } from './client'

export interface PolicyProfile {
  value: string
  label: string
  description?: string
}

export function listProfiles(): Promise<PolicyProfile[]> {
  return apiGet<PolicyProfile[]>('/api/profiles')
}

/** Present only when a previous Protected Run on this workspace crashed
 * without being cleaned up -- session_id is the run that must be
 * reconciled (see reconcileRun) before a new run can use this workspace. */
export interface WorkspaceRecovery {
  required: boolean
  session_id?: string
  status?: string
  action?: string | null
  agent_process_status?: string | null
}

export interface WorkspaceValidation {
  valid: boolean
  exists?: boolean
  is_directory?: boolean
  canonical_path?: string
  error?: string
  recovery?: WorkspaceRecovery | null
}

export function validateWorkspace(path: string): Promise<WorkspaceValidation> {
  return apiGet<WorkspaceValidation>(`/api/workspaces/validate?path=${encodeURIComponent(path)}`)
}

export interface ReconcileResult {
  reconciled: boolean
  session_id: string
  reason?: string
  runtime_reconciliation?: Record<string, unknown>
}

/** Non-throwing: a refused reconcile (still-live coordinator or Agent root)
 * comes back as a 409 with a `reason` code and no `error` key, which the
 * normal apiPost would discard on a thrown Error. Never force-releases the
 * workspace lease directly -- this runs the same identity-verified checks
 * as `aia reconcile <session_id>` (see service.py's reconcile_orphaned_run):
 * it only succeeds once the crashed run's AIA coordinator AND its Codex
 * Agent root are both provably gone. */
export function reconcileRun(sessionId: string): Promise<ReconcileResult> {
  return apiPostTolerant<ReconcileResult>(`/api/runs/${encodeURIComponent(sessionId)}/reconcile`)
}

export interface CreateRunPayload {
  workspace: string
  agent?: string
  model?: string | null
  policy_profile?: string
  mode?: string
  interactive?: boolean
  launch_mode?: 'inherit' | 'new_terminal' | 'codex_app_server'
}

export interface CreateRunResult {
  session_id: string
  redirect_url?: string
  status?: string
}

export function createProtectedRun(payload: CreateRunPayload): Promise<CreateRunResult> {
  return apiPost<CreateRunResult>('/api/runs', payload)
}

export interface HookSetupResult {
  installed: boolean
  hook_path?: string
  posttool_installed?: boolean
  trust_required?: boolean
  next_step?: string
  error?: string
}

export function installHook(): Promise<HookSetupResult> {
  return apiPost<HookSetupResult>('/api/hook/setup')
}

export interface HookVerifyResult {
  verified: boolean
  reason?: string
  next_step?: string
  protection_claim?: string
  session_id?: string
  hook_event_count?: number
  trust_status?: string
}

/** Non-throwing: /api/hook/verify's 409/502/503/504 bodies carry
 * reason/next_step with no `error` key, which the normal apiPost would
 * discard on a thrown Error. */
export function verifyHook(): Promise<HookVerifyResult> {
  return apiPostTolerant<HookVerifyResult>('/api/hook/verify')
}

export interface ConsoleInfo {
  cli_prefix: string
  module_cli_prefix: string
  cli_project_root: string | null
  hook_path: string
}

export function consoleInfo(): Promise<ConsoleInfo> {
  return apiGet<ConsoleInfo>('/api/console-info')
}
