import type { IncidentView, UnevaluatedObservationView } from '../../api/resultTypes'

// The evidence view renders only presenter-approved fields. The separate
// observation section never includes raw commands or process paths.
export function EvidenceLogView({
  incidents,
  unevaluatedObservations = [],
}: {
  incidents: IncidentView[]
  unevaluatedObservations?: UnevaluatedObservationView[]
}) {
  if (incidents.length === 0 && unevaluatedObservations.length === 0) {
    return <p className="faint-note">기록된 정책 사건이나 판정 불가 프로세스 관찰이 없어요.</p>
  }

  return (
    <div className="evidence-log">
      {incidents.length > 0 && (
        <section aria-label="정책 사건 로그">
          <h3>정책 사건</h3>
          <pre>
            {incidents.map((incident, index) => (
              <div key={incident.action_id ?? index} className="evidence-log-entry">
                {'action=' + (incident.action_id ?? '-') + '  operation=' + (incident.operation ?? '-') + '  effect=' + (incident.policy_effect ?? '-') + '\n'}
                {'  attribution=' + (incident.attribution_class ?? '-') + '  enforcement=' + (incident.enforcement_action ?? '-') + '  execution=' + (incident.execution_result ?? 'NOT_REPORTED') + '\n'}
                {'  target=' + (incident.target?.display ?? '-') + '\n'}
                {incident.summary ? '  summary: ' + incident.summary + '\n' : ''}
                {incident.reason ? '  reason: ' + incident.reason + '\n' : ''}
              </div>
            ))}
          </pre>
        </section>
      )}
      {unevaluatedObservations.length > 0 && (
        <section aria-label="판정하지 못한 프로세스 관찰">
          <h3>판정하지 못한 프로세스 관찰</h3>
          <ul>
            {unevaluatedObservations.map((observation, index) => (
              <li key={observation.process_name + index} className="evidence-log-entry">
                {observation.process_name} · {observation.process_role} · {observation.reason_code}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}
