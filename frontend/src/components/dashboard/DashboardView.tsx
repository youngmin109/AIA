import { useShellStore } from '../../state/shellStore'
import { useRunStatus } from '../../hooks/useRunStatus'
import { GuardianHero } from './GuardianHero'
import { DashboardPanel } from './DashboardPanel'
import { SensorHealthRow } from '../sensors/SensorHealthRow'
import { EventFeed } from '../sensors/EventFeed'
import { Icon } from '../common/Icon'
import { usePreflight } from '../../hooks/usePreflight'

export function DashboardView() {
  const { activeRunId, setView } = useShellStore()
  const { data: status } = useRunStatus(activeRunId, { enabled: Boolean(activeRunId) })
  const { data: preflight } = usePreflight()

  if (!activeRunId) {
    const protectedRunReady = preflight?.readiness_code === 'READY'
    if (protectedRunReady) {
      return (
        <div className="dashboard-view">
          <div className="dashboard-grid">
            <GuardianHero />
            <aside className="dashboard-rightcol">
              <div className="card dashboard-card">
                <div className="dashboard-card-title">보호 실행 준비 완료</div>
                <div className="dashboard-card-desc">Hook 연결이 검증되었습니다. Workspace를 선택해 보호 실행을 시작할 수 있습니다.</div>
                <DashboardPanel />
              </div>
            </aside>
          </div>
          <div className="card guardian-ready-brief">
            <div>
              <div className="dashboard-card-title">이제 실제 작업을 시작할 수 있어요</div>
              <div className="dashboard-card-desc">보호 실행을 시작하면 Agent CLI, Process Tree, 파일 변경과 정책 사건이 실제 세션 데이터로 채워집니다.</div>
            </div>
            <div className="guardian-ready-checks">
              {(preflight.checks ?? []).map((check) => (
                <span key={check.name} className={check.ok ? 'is-ok' : 'is-warn'}>{check.ok ? '●' : '●'} {check.label}</span>
              ))}
            </div>
          </div>
        </div>
      )
    }
    return (
      <div className="dashboard-view">
        <div style={{ maxWidth: 620, margin: '24px auto 0', display: 'grid', gap: 14 }}>
          <GuardianHero />
          <div className="card dashboard-card">
            <DashboardPanel />
          </div>
        </div>
      </div>
    )
  }

  const summary = status?.evidence_summary
  const metrics = [
    { label: '세션 누적 프로세스', value: summary?.process_observed ?? 0, hint: '시작 이후 관찰된 수' },
    { label: 'Hook 이벤트', value: (summary?.pretool_events ?? 0) + (summary?.posttool_events ?? 0), hint: '실행 전/후 요청 수신' },
    { label: 'Workspace 파일 변경', value: summary?.filesystem_events ?? 0, hint: '생성·수정·삭제 합계' },
    { label: '정책 사건', value: status?.incident_count ?? 0, hint: '확인이 필요한 사건 수' },
  ]

  return (
    <div className="dashboard-view">
      <div className="dashboard-metrics">
        {metrics.map((metric) => (
          <div key={metric.label} className="card dashboard-metric">
            <div className="dashboard-metric-label">{metric.label}</div>
            <div className="dashboard-metric-value">{metric.value}</div>
            <div className="dashboard-metric-hint">{metric.hint}</div>
          </div>
        ))}
      </div>

      <div className="dashboard-grid">
        <GuardianHero />
        <aside className="dashboard-rightcol">
          <div className="card dashboard-card">
            <div className="dashboard-card-title">런타임 센서</div>
            <div className="dashboard-card-desc">실제 실행 사실을 독립적으로 관찰합니다.</div>
            <SensorHealthRow sensorHealth={status?.sensor_health} evidenceSummary={status?.evidence_summary} />
          </div>
          <div className="card dashboard-card">
            <div className="dashboard-card-title">Codex 작업 공간</div>
            <div className="dashboard-card-desc">명령은 Agent CLI에서 입력하고 AIA가 실행 전 확인합니다.</div>
            <button type="button" className="dashboard-launch-btn" onClick={() => setView('terminal')}>
              <Icon name="terminal" size={20} />
              <span>
                <b>Agent CLI 열기</b>
                <small>Codex 세션 연결됨</small>
              </span>
              <strong>→</strong>
            </button>
          </div>
        </aside>
      </div>

      <div className="card dashboard-activity-card">
        <div className="dashboard-activity-head">
          <div>
            <div className="dashboard-card-title">최근 활동</div>
            <div className="dashboard-card-desc">요청 · 실행 · 파일 변경을 한 흐름으로 보여줍니다.</div>
          </div>
        </div>
        <EventFeed runId={activeRunId} events={status?.events} evidenceChains={status?.evidence_chains} limit={5} />
      </div>
    </div>
  )
}
