import { useShellStore } from '../../state/shellStore'

// Milestone 3: static mock data standing in for GET /api/runs filtered to
// completed/stopped sessions. Replaced with real data + GET
// /api/runs/{id}/result drill-in during milestone 5.
const MOCK_RESULTS = [
  { id: 'run-41274c13', workspace: 'C:\\workspace\\aia-demo-hanbit', bundle: '유효', tone: 'ok' as const },
  { id: 'run-22b7cf1c', workspace: 'C:\\workspace\\aia-demo-hanbit', bundle: '유효 · 정책 사건 2건', tone: 'warn' as const },
]

export function ResultsListPanel() {
  const { openTab, activeTabId } = useShellStore()

  return (
    <div className="run-list">
      {MOCK_RESULTS.map((run) => (
        <button
          key={run.id}
          type="button"
          className={`run-row${activeTabId === run.id ? ' is-active' : ''}`}
          onClick={() => openTab({ id: run.id, title: `${run.id.replace('run-', '#')} 결과` })}
        >
          <div className="run-row-top">
            <span>{run.id.replace('run-', '#')}</span>
            <span className={`badge is-${run.tone}`}>{run.bundle}</span>
          </div>
          <div className="run-row-path" title={run.workspace}>
            {run.workspace}
          </div>
        </button>
      ))}
    </div>
  )
}
