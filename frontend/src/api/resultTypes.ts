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

export interface ResultView {
  bundle_status?: string
  launch_mode?: string
  session_status?: string
  recovery_status?: string
  integrity_status?: string
  policy_id?: string
  policy_version?: string
  workspace?: string
  incidents?: IncidentView[]
  incident_count?: number
  sensor_summary?: Array<{ sensor?: string; runtime_health_before_stop?: string; final_sensor_state?: string }>
  result_available?: boolean
  protection_state?: string
  execution_policy_status?: string
  [key: string]: unknown
}
