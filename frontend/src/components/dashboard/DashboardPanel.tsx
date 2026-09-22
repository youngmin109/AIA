import { useState } from 'react'
import { useShellStore } from '../../state/shellStore'
import { usePreflight } from '../../hooks/usePreflight'
import { useRunList } from '../../hooks/useRunList'

const READINESS_LABELS: Record<string, string> = {
  READY: '준비 완료',
  HOOK_VERIFICATION_REQUIRED: '확인 필요',
  CODEX_HOOK_TRUST_REQUIRED: 'Hook 검토 필요',
  CODEX_HOOK_NOT_INSTALLED: 'Hook 설치 필요',
  CODEX_EXECUTABLE_UNAVAILABLE: 'Codex 확인 필요',
  PREFLIGHT_TIMEOUT: '확인 시간 초과',
  PREFLIGHT_UNAVAILABLE: '확인 실패',
  CHECKING: '확인 중',
  UNKNOWN: '확인 필요',
}

const TRUST_LABELS: Record<string, string> = {
  TRUSTED: '신뢰됨',
  MANAGED: '관리됨',
  MANUAL_REVIEW_REQUIRED: '검토 필요',
  MODIFIED: '변경됨 · 검토 필요',
  UNTRUSTED: '신뢰되지 않음',
  CHECKING: '확인 중',
  UNKNOWN: '확인 필요',
}

export function DashboardPanel() {
  const { openSettingsModal, setActiveRun, setView } = useShellStore()
  const [devSessionId, setDevSessionId] = useState('')
  const { data: preflight, isLoading: preflightLoading } = usePreflight()
  const { data: runs } = useRunList()

  const readinessCode = preflight?.readiness_code ?? (preflightLoading ? 'CHECKING' : 'UNKNOWN')
  const readinessTone = readinessCode === 'READY' ? 'ok' : 'warn'
  const hookTrustStatus = preflight?.hook_trust?.status ?? 'UNKNOWN'
  const hookTrustTone = ['TRUSTED', 'MANAGED'].includes(hookTrustStatus) ? 'ok' : 'warn'

  const activeRuns = (runs ?? []).filter((run) => run.status === 'RUNNING').length
  const totalRuns = runs?.length ?? 0

  return (
    <div>
      <div className="panel-section">
        <p className="panel-section-title">보호 상태</p>
        <div className="stat-card">
          <div className="stat-card-label">준비 상태</div>
          <div className={`stat-card-value is-${readinessTone}`}>{READINESS_LABELS[readinessCode] ?? readinessCode}</div>
        </div>
        <div className="stat-card">
          <div className="stat-card-label">Codex Hook 신뢰 상태</div>
          <div className={`stat-card-value is-${hookTrustTone}`}>{TRUST_LABELS[hookTrustStatus] ?? hookTrustStatus}</div>
        </div>
        <div className="stat-card">
          <div className="stat-card-label">지원 Agent</div>
          <div className="stat-card-value">Codex CLI</div>
        </div>
      </div>

      <div className="panel-section">
        <p className="panel-section-title">실행 현황</p>
        <div className="stat-card">
          <div className="stat-card-label">현재 진행 중</div>
          <div className="stat-card-value">{activeRuns}건</div>
        </div>
        <div className="stat-card">
          <div className="stat-card-label">전체 보호 실행</div>
          <div className="stat-card-value">{totalRuns}건</div>
        </div>
      </div>

      <button type="button" className="cta-button" onClick={openSettingsModal}>
        + 새 보호 실행 시작
      </button>

      {/* TEMPORARY dev aid: opens any session_id as a tab directly, useful
          while verifying real backend wiring. Safe to keep -- harmless if
          unused, and occasionally useful for support/debugging later. */}
      <div className="panel-section" style={{ marginTop: 18 }}>
        <p className="panel-section-title">세션 ID로 열기</p>
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
            onClick={() => {
              if (!devSessionId.trim()) return
              setActiveRun(devSessionId.trim())
              setView('terminal')
            }}
          >
            열기
          </button>
        </div>
      </div>
    </div>
  )
}
