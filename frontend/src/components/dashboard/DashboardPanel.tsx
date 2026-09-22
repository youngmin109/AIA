import { useShellStore } from '../../state/shellStore'

// Milestone 3: static mock data. Replaced with a live GET /api/preflight
// poll (usePreflight) in milestone 5.
const MOCK_READINESS = {
  sensors: { label: '준비 완료', tone: 'ok' as const },
  hookTrust: { label: '신뢰됨', tone: 'ok' as const },
  agent: 'Codex CLI',
  activeRuns: 0,
  totalRuns: 135,
}

export function DashboardPanel() {
  const { openSettingsModal } = useShellStore()

  return (
    <div>
      <div className="panel-section">
        <p className="panel-section-title">보호 상태</p>
        <div className="stat-card">
          <div className="stat-card-label">센서 준비</div>
          <div className={`stat-card-value is-${MOCK_READINESS.sensors.tone}`}>
            {MOCK_READINESS.sensors.label}
          </div>
        </div>
        <div className="stat-card">
          <div className="stat-card-label">Codex Hook 신뢰 상태</div>
          <div className={`stat-card-value is-${MOCK_READINESS.hookTrust.tone}`}>
            {MOCK_READINESS.hookTrust.label}
          </div>
        </div>
        <div className="stat-card">
          <div className="stat-card-label">지원 Agent</div>
          <div className="stat-card-value">{MOCK_READINESS.agent}</div>
        </div>
      </div>

      <div className="panel-section">
        <p className="panel-section-title">실행 현황</p>
        <div className="stat-card">
          <div className="stat-card-label">현재 진행 중</div>
          <div className="stat-card-value">{MOCK_READINESS.activeRuns}건</div>
        </div>
        <div className="stat-card">
          <div className="stat-card-label">전체 보호 실행</div>
          <div className="stat-card-value">{MOCK_READINESS.totalRuns}건</div>
        </div>
      </div>

      <button type="button" className="cta-button" onClick={openSettingsModal}>
        + 새 보호 실행 시작
      </button>
    </div>
  )
}
