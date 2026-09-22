import { apiGet, apiPost } from './client'

export interface PolicyProfile {
  value: string
  label: string
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
