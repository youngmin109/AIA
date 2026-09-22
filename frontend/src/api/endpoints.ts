import { apiGet, apiPost, apiPostTolerant } from './client'

export interface PolicyProfile {
  value: string
  label: string
  description?: string
}

export function listProfiles(): Promise<PolicyProfile[]> {
  return apiGet<PolicyProfile[]>('/api/profiles')
}

export interface WorkspaceValidation {
  valid: boolean
  exists?: boolean
  is_directory?: boolean
  canonical_path?: string
  error?: string
}

export function validateWorkspace(path: string): Promise<WorkspaceValidation> {
  return apiGet<WorkspaceValidation>(`/api/workspaces/validate?path=${encodeURIComponent(path)}`)
}

export interface CreateRunPayload {
  workspace: string
  agent?: string
  model?: string | null
  policy_profile?: string
  mode?: string
  interactive?: boolean
  launch_mode?: 'inherit' | 'new_terminal' | 'web_terminal'
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
