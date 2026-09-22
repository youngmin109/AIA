import { useShellStore } from '../../state/shellStore'

// Milestone 3: static mock data standing in for GET /api/preflight +
// GET /api/runs (active-run count). Wired to real polling in milestone 5.
export function StatusBar() {
  const { openTabs } = useShellStore()

  return (
    <div className="status-bar">
      <span className="status-bar-item">
        <span className="status-dot is-ok" />
        Hook Trust: 신뢰됨
      </span>
      <span className="status-bar-item">
        <span className="status-dot is-ok" />
        로컬 서버 연결됨
      </span>
      <span className="status-bar-item">활성 세션 {openTabs.length}건</span>
      <div className="status-bar-spacer" />
      <span>AIA · 로컬 전용 콘솔</span>
    </div>
  )
}
