// Shapes mirror aia_app.service.RunApplicationService.get_run_status() /
// list_runs() JSON responses. Typed narrowly to the fields this frontend
// actually reads; unknown additional fields pass through untyped rather
// than being exhaustively modeled (no codegen from the Python side yet).

export interface TerminalSnapshot {
  mode?: string
  status?: string
  pid?: number | null
  rows?: number
  cols?: number
  started_at?: string | null
  ended_at?: string | null
  exit_code?: number | null
  error?: string | null
}

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
  observed_at?: string
  incident_action_id?: string
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
  terminal?: TerminalSnapshot
  events?: SecurityEvent[]
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
