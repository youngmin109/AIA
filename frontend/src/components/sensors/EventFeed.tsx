import { useRunStatus } from '../../hooks/useRunStatus'

function toneFor(decision: string | undefined): 'ok' | 'warn' | 'bad' {
  const upper = String(decision || '').toUpperCase()
  if (['VIOLATION', 'DENY', 'REFUSE'].includes(upper)) return 'bad'
  if (['VALID', 'ALLOW', 'NONE', ''].includes(upper)) return 'ok'
  return 'warn'
}

export function EventFeed({ runId, isFocused }: { runId: string | null; isFocused: boolean }) {
  const { data: status } = useRunStatus(runId, { enabled: isFocused && Boolean(runId) })
  const events = status?.events ?? []

  if (!runId) {
    return <p className="empty-hint">열린 실행을 선택하면 Hook·File·Process 센서 기록이 여기에 표시됩니다.</p>
  }
  if (events.length === 0) {
    return <p className="empty-hint">아직 관찰된 센서 이벤트가 없습니다.</p>
  }

  return (
    <div className="event-list">
      {events
        .slice()
        .reverse()
        .map((event, index) => (
          <div key={event.event_id ?? index} className="event-row">
            <div className="event-row-top">
              <span className="event-row-sensor">{event.sensor ?? event.origin_label ?? '센서'}</span>
              <span className={`badge is-${toneFor(event.display_decision ?? event.decision)}`}>
                {event.display_decision ?? event.decision ?? '확인 필요'}
              </span>
            </div>
            <span>{event.display_summary ?? event.summary}</span>
          </div>
        ))}
    </div>
  )
}
