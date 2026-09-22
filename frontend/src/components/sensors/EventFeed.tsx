// Milestone 3: static mock data standing in for the `events` array already
// returned by GET /api/runs/{session_id} (polled every 1s while a run tab
// is focused). Wired to real polling in milestone 5.
const MOCK_EVENTS = [
  { sensor: 'HOOK', summary: '명령 실행 요청 · 판정 불가', decision: 'warn' as const },
  { sensor: 'FILE', summary: '파일 변경 관찰 · 정상', decision: 'ok' as const },
  { sensor: 'PROCESS', summary: 'Agent 자식 프로세스 관찰', decision: 'ok' as const },
]

export function EventFeed({ runId }: { runId: string | null }) {
  if (!runId) {
    return <p className="empty-hint">열린 실행을 선택하면 Hook·File·Process 센서 기록이 여기에 표시됩니다.</p>
  }

  return (
    <div className="event-list">
      {MOCK_EVENTS.map((event, index) => (
        <div key={index} className="event-row">
          <div className="event-row-top">
            <span className="event-row-sensor">{event.sensor}</span>
            <span className={`badge is-${event.decision}`}>{event.decision === 'ok' ? '정상' : '확인 필요'}</span>
          </div>
          <span>{event.summary}</span>
        </div>
      ))}
    </div>
  )
}
