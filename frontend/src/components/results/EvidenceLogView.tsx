import type { IncidentView } from '../../api/resultTypes'

// Renders already-redacted fields (the same ones IncidentRow's expanded
// view already shows) as a monospace log block, matching the Guardian
// mockup's raw-evidence aesthetic -- never the raw command/secret text
// presenters.py strips before it reaches the frontend.
export function EvidenceLogView({ incidents }: { incidents: IncidentView[] }) {
  if (incidents.length === 0) {
    return <p className="faint-note">기록된 정책 사건이 없어요.</p>
  }

  return (
    <pre className="evidence-log">
      {incidents.map((incident, index) => (
        <div key={incident.action_id ?? index} className="evidence-log-entry">
          {`action=${incident.action_id ?? '-'}  operation=${incident.operation ?? '-'}  effect=${incident.policy_effect ?? '-'}\n`}
          {`  attribution=${incident.attribution_class ?? '-'}  enforcement=${incident.enforcement_action ?? '-'}  execution=${incident.execution_result ?? 'NOT_REPORTED'}\n`}
          {`  target=${incident.target?.display ?? '-'}\n`}
          {incident.summary ? `  summary: ${incident.summary}\n` : ''}
          {incident.reason ? `  reason: ${incident.reason}\n` : ''}
        </div>
      ))}
    </pre>
  )
}
