// Shapes mirror aia_app.service.RunApplicationService.get_run_status() /
// list_runs() JSON responses. Typed narrowly to the fields this frontend
// actually reads; unknown additional fields pass through untyped rather
// than being exhaustively modeled (no codegen from the Python side yet).

import type { StartupInfo } from './startupStatus'
import type { PermissionGrant } from './permissionGrants'

export interface SecurityEvent {
  event_id?: string
  category?: string
  summary?: string
  display_summary?: string
  origin_label?: string
  sensor?: string
  severity?: string
  decision?: string
  display_decision?: string
  execution_result?: string
  execution_observed?: boolean
  observed_at?: string
  incident_action_id?: string
  chain_action_id?: string
  tool_name?: string
  target_label?: string
}

export interface EvidenceChainSensorLink {
  sensor?: string
  status?: string
  evidence_count?: number
  run_evidence_count?: number
}

export interface EvidenceChainStage {
  stage?: string
  label?: string
  status?: string
}

export interface EvidenceChain {
  action_id?: string
  operation?: string
  target_label?: string
  observed_at?: string
  evidence_link_status?: string
  linked_evidence_count?: number
  evidence_count?: number
  sensor_links?: EvidenceChainSensorLink[]
  stages?: EvidenceChainStage[]
}

export interface EvidenceTimelineRecord {
  evidence_id?: string
  source?: string
  record_type?: string
  captured_at?: string
  link_status?: string
  linked_action_id?: string
}

export interface EvidenceSummary {
  available?: boolean
  pretool_events?: number
  posttool_events?: number
  filesystem_events?: number
  process_observed?: number
  process_exit_observed?: number
  sensor_health_events?: number
}

export interface RunStatus {
  startup?: StartupInfo
  permission_grants?: PermissionGrant[]
  codex_thread_id?: string | null
  resumed_from?: string | null
  activity?: {
    available?: boolean; live?: boolean; current_alive_count?: number | null; unique_file_count?: number;
    process_identity_count?: number; truncated?: boolean;
    files?: Array<{ path: string; event_type: string; event_count: number; observed_at: string; evidence_id: string }>;
    processes?: Array<{ pid: number; create_time: number; parent_pid?: number; parent_create_time?: number; name: string; role: string; state: string; observed_at: string; evidence_id: string }>;
  }
  session?: {
    session_id?: string
    agent?: string
    model?: string
    status?: string
    workspace?: string
    created_at?: string
    launch_mode?: string
  }
  policy?: { id?: string; profile?: string; version?: string }
  protection?: { state?: string; hook_events?: number; hook_broker?: string }
  runtime_reconciliation?: { orphaned?: boolean; [key: string]: unknown }
  events?: SecurityEvent[]
  sensor_health?: Record<string, string>
  evidence_summary?: EvidenceSummary
  evidence_chains?: EvidenceChain[]
  evidence_timeline?: EvidenceTimelineRecord[]
  incident_count?: number
  bundle_status?: string
  result_available?: boolean
  stop?: { requested?: boolean; error?: string | null }
  error?: string | null
  [key: string]: unknown
}

export interface RunSummary {
  session_id: string
  status?: string
  created_at?: string
  workspace?: string
  agent?: string
  policy?: { id?: string; version?: string }
  run_classification?: string
  bundle_status?: string
  incident_count?: number
  result_url?: string
  protection_state?: string
  launch_mode?: string
  [key: string]: unknown
}
