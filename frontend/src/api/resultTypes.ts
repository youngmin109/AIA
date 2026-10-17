// Loosely typed mirror of aia_app.presenters.result_view()/incident_view().
// Only the fields this frontend renders are named; the rest pass through.

export interface IncidentView {
  action_id?: string
  operation?: string
  policy_effect?: string
  attribution_class?: string
  enforcement_action?: string
  execution_result?: string
  summary?: string
  reason?: string
  proof?: string
  target?: { display?: string }
  [key: string]: unknown
}

export interface UnevaluatedObservationView {
  process_name: string
  process_role: string
  reason_code: string
}

export interface UnevaluatedObservationsView {
  count: number
  items: UnevaluatedObservationView[]
}

export interface ResultView {
  bundle_status?: string
  launch_mode?: string
  session_status?: string
  limitations?: string[]
  unsupported_tool_review_decisions?: Array<
    | 'UNSUPPORTED_TOOL_REVIEW_APPROVED'
    | 'UNSUPPORTED_TOOL_REVIEW_DECLINED'
    | 'UNSUPPORTED_TOOL_REVIEW_TIMED_OUT'
  >
  recovery_status?: string
  integrity_status?: string
  policy_id?: string
  policy_version?: string
  workspace?: string
  incidents?: IncidentView[]
  incident_count?: number
  unevaluated_observations?: UnevaluatedObservationsView
  attribution_summary?: {
    counts?: Record<'EXACT' | 'PROCESS' | 'TEMPORAL' | 'UNKNOWN', number>
    automatic_control_happened?: boolean
    automatic_control_grades?: string[]
  }
  result_action_chains?: Array<{
    action_id?: string
    stages?: Array<{ stage?: string; label?: string; status?: string; value?: string }>
  }>
  sensor_summary?: Array<{ sensor?: string; runtime_health_before_stop?: string; final_sensor_state?: string }>
  result_available?: boolean
  protection_state?: string
  execution_policy_status?: string
  [key: string]: unknown
}

export interface RecoveryStatusView {
  checkpoint_id?: string;
  checkpoint_created_at?: string;
  preview_fingerprint?: string;
  change_count?: number;
  change_preview?: Array<{ path: string; operation: string }>;
  preview_truncated?: boolean;
  record_verification?: string;
  recovery_status?: string
  integrity_status?: string
  mismatched_file_count?: number | null
  /** Manual Workspace restore can run (run ended and a valid checkpoint exists). */
  available?: boolean
  reason?: string | null
  /** The Workspace currently equals the run's pre-run checkpoint. */
  workspace_matches?: boolean
  manual_recovery?: boolean
}
