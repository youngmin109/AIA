// Shapes mirror aia_app.service.RunApplicationService.get_run_status() /
// list_runs() JSON responses. Typed narrowly to the fields this frontend
// actually reads; unknown additional fields pass through untyped rather
// than being exhaustively modeled (no codegen from the Python side yet).

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
