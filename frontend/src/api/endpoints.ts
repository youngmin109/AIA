import type { CodexModel } from './modelView'
import type { CodexConnector } from './connectorView'
import type { StoragePruneResult, StorageSummary } from './storageView'
import type { ExternalToolsState } from './externalToolsView'
import type { PermissionMode } from './permissionMode'
import { apiGet, apiPost, apiPostTolerant } from './client'

export interface PolicyProfile {
  value: string
  display_name: string
  english_name?: string
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
  size_estimate?: WorkspaceSizeEstimate | null
}

export interface WorkspaceSizeEstimate { files: number; bytes: number; complete: boolean }

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

/** Restores the whole Workspace of an ended run to its pre-run checkpoint and
 * re-verifies it with SHA-256 (service.py restore_run). The server refuses
 * without `confirm: true`, so callers must ask the user first. */
export function restoreWorkspace(sessionId: string, fingerprint: string, checkpointId?: string): Promise<Record<string, unknown>> {
  return apiPost<Record<string, unknown>>(`/api/runs/${encodeURIComponent(sessionId)}/recovery/restore`, { confirm: true, expected_fingerprint: fingerprint, ...(checkpointId ? { checkpoint_id: checkpointId } : {}) })
}

export interface CreateRunPayload {
  workspace: string
  agent?: string
  model?: string | null
  policy_profile?: string
  custom_policy_path?: string
  mode?: string
  interactive?: boolean
  launch_mode?: 'inherit' | 'new_terminal' | 'codex_app_server'
  reasoning_effort?: string | null
  resume_thread_id?: string | null
  /** Files and folders inside the workspace to protect on top of the policy. */
  protected_paths?: string[]
  /** AI permission: full access (YOLO) or the work folder only. */
  permission_mode?: PermissionMode
}

export interface CreateRunResult {
  session_id: string
  redirect_url?: string
  status?: string
}

export function storageSummary(): Promise<StorageSummary> {
  return apiGet<StorageSummary>('/api/storage')
}

export function pruneStorage(): Promise<StoragePruneResult> {
  return apiPost<StoragePruneResult>('/api/storage/prune', {})
}

/** Codex external tools and which ones AIA's protected runs keep on. */
export function externalTools(): Promise<ExternalToolsState> {
  return apiGet<ExternalToolsState>('/api/external-tools')
}

export function setExternalTools(allowed: string[]): Promise<ExternalToolsState> {
  return apiPost<ExternalToolsState>('/api/external-tools', { allowed })
}

export async function createProtectedRun(payload: CreateRunPayload): Promise<CreateRunResult> {
  const result = await apiPost<CreateRunResult>('/api/runs', payload)
  window.dispatchEvent(new Event('aia:runs-updated'))
  return result
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
  product_version?: string
  supported_environment?: string
  cli_prefix: string
  module_cli_prefix: string
  cli_project_root: string | null
  hook_path: string
}

export function consoleInfo(): Promise<ConsoleInfo> {
  return apiGet<ConsoleInfo>('/api/console-info')
}

/** Connectors (MCP servers) of an open conversation; view only. */
export function codexConnectors(runId: string): Promise<{ connectors: CodexConnector[] }> {
  return apiGet<{ connectors: CodexConnector[] }>(`/api/runs/${encodeURIComponent(runId)}/codex/connectors`)
}

/** One request's diff (or the whole conversation's when turnId is null); kept in memory only. */
export function codexDiff(runId: string, turnId: string | null): Promise<{ diff: string; truncated: boolean }> {
  const query = turnId ? `?turn_id=${encodeURIComponent(turnId)}` : ''
  return apiGet<{ diff: string; truncated: boolean }>(`/api/runs/${encodeURIComponent(runId)}/codex/diff${query}`)
}

/** A Codex conversation an earlier AIA run opened; name and preview are read live from Codex. */
export interface ResumableConversation {
  session_id: string
  thread_id: string
  workspace: string
  created_at?: string | null
  status?: string | null
  name?: string | null
  preview?: string
  updated_at?: string | null
  missing?: boolean | null
}

export function codexConversations(): Promise<{ conversations: ResumableConversation[]; error?: string }> {
  return apiGet<{ conversations: ResumableConversation[]; error?: string }>('/api/codex/conversations')
}

/** Visible Codex models from a short-lived app-server; an empty list hides the pickers. */
export function codexModels(): Promise<{ models: CodexModel[]; error?: string }> {
  return apiGet<{ models: CodexModel[]; error?: string }>('/api/codex/models')
}
