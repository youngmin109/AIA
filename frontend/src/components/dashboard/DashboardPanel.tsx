import { useState } from 'react'
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
  const { openSettingsModal, openTab } = useShellStore()
  const [devSessionId, setDevSessionId] = useState('')

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

      {/* TEMPORARY (milestone 4 dev aid): real run-list wiring lands in
          milestone 5's "새 보호 실행 시작" flow; until then this is the only
          way to open a real session_id as a tab for terminal-port testing.
          Remove once the setup modal creates + opens tabs itself. */}
      <div className="panel-section" style={{ marginTop: 18 }}>
        <p className="panel-section-title">개발용 · 세션 ID로 열기</p>
        <div style={{ display: 'flex', gap: 6 }}>
          <input
            value={devSessionId}
            onChange={(event) => setDevSessionId(event.target.value)}
            placeholder="session_id"
            style={{ flex: 1, minWidth: 0, padding: '6px 8px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg-inset)', color: 'var(--text)' }}
          />
          <button
            type="button"
            className="icon-button-text"
            onClick={() => devSessionId.trim() && openTab({ id: devSessionId.trim(), title: `#${devSessionId.trim().slice(0, 8)}` })}
          >
            열기
          </button>
        </div>
      </div>
    </div>
  )
}
