import { useShellStore } from '../../state/shellStore'

// Milestone 3: static mock data standing in for GET /api/runs.
// Replaced with useRunList() in milestone 5; shape mirrors the real
// service.list_runs() fields (workspace, status, incident_count, ...).
const MOCK_RUNS = [
  { id: 'run-7a5bfbb4', workspace: 'C:\\workspace\\aia-demo-hanbit', status: '사용자 중지', tone: 'warn' as const, incidents: 1 },
  { id: 'run-41274c13', workspace: 'C:\\workspace\\aia-demo-hanbit', status: '중지 · 검증됨', tone: 'ok' as const, incidents: 1 },
  { id: 'run-cbc4927f', workspace: 'C:\\workspace\\aia-protected-diagnostic', status: '보호 실패', tone: 'bad' as const, incidents: 0 },
]

export function RunListPanel() {
  const { openTab, activeTabId } = useShellStore()

  return (
    <div className="run-list">
      {MOCK_RUNS.map((run) => (
        <button
          key={run.id}
          type="button"
          className={`run-row${activeTabId === run.id ? ' is-active' : ''}`}
          onClick={() => openTab({ id: run.id, title: run.id.replace('run-', '#') })}
        >
          <div className="run-row-top">
            <span>{run.id.replace('run-', '#')}</span>
            <span className={`badge is-${run.tone}`}>{run.status}</span>
            {run.incidents > 0 && <span className="badge is-warn">사건 {run.incidents}</span>}
          </div>
          <div className="run-row-path" title={run.workspace}>
            {run.workspace}
          </div>
        </button>
      ))}
    </div>
  )
}
