import { useShellStore } from '../../state/shellStore'
import { useRunStatus } from '../../hooks/useRunStatus'
import { usePreflight } from '../../hooks/usePreflight'
import { GuardianHero } from './GuardianHero'
import { SensorHealthRow } from '../sensors/SensorHealthRow'
import { EventFeed } from '../sensors/EventFeed'
import { Icon } from '../common/Icon'

/** One stable Guardian layout: readiness changes data, not the whole screen. */
export function DashboardView() {
  const { activeRunId, setView, openSettingsModal } = useShellStore()
  const { data: status } = useRunStatus(activeRunId, { enabled: Boolean(activeRunId) })
  const { data: preflight } = usePreflight()
  const summary = status?.evidence_summary
  const isActive = Boolean(activeRunId)
  const healthyChecks = (preflight?.checks ?? []).filter((check) => check.ok).length
  const metrics = [
    { label: '세션 누적 프로세스', value: isActive ? summary?.process_observed ?? 0 : '—', hint: isActive ? '세션에서 관찰된 Process 이벤트' : '보호 실행 시작 후 표시' },
    { label: 'Hook 요청', value: isActive ? (summary?.pretool_events ?? 0) + (summary?.posttool_events ?? 0) : '—', hint: isActive ? '실행 전·후 요청 수신' : 'Hook 연결은 준비됨' },
    { label: 'Workspace 파일 변경', value: isActive ? summary?.filesystem_events ?? 0 : '—', hint: isActive ? '실제 File Sensor 이벤트' : '보호 실행 시작 후 표시' },
    { label: '정책 판정 결과', value: isActive ? status?.incident_count ?? 0 : '—', hint: isActive ? '위험·확인 필요 사건 수' : '정책은 다음 실행에서 적용' },
  ]

  return (
    <div className="dashboard-view guardian-dashboard">
      {/* The page title lives in the topbar; the dashboard opens with status. */}
      <div className="dashboard-top">
        <GuardianHero
          readiness={preflight ? `보호 조건 ${healthyChecks}개 정상` : '보호 조건 확인 중'}
          ready={preflight?.readiness_code === 'READY'}
        />
        <div className="dashboard-metrics">
          {metrics.map((metric) => <div key={metric.label} className="card dashboard-metric"><div className="dashboard-metric-label">{metric.label}</div><div className="dashboard-metric-value">{metric.value}</div><div className="dashboard-metric-hint">{metric.hint}</div></div>)}
        </div>
      </div>
      <div className="dashboard-grid">
        <div className="card dashboard-card">
          <div className="dashboard-card-title">런타임 센서</div>
          <div className="dashboard-card-desc">Agent 요청과 실제 실행·파일 변화를 서로 독립적으로 확인합니다.</div>
          {isActive ? <SensorHealthRow sensorHealth={status?.sensor_health} evidenceSummary={summary} /> : <div className="sensor-explainer"><span>● PreTool Hook <small>실행 전 요청 수신</small></span><span>● File Sensor <small>Workspace 파일 변화 감시</small></span><span>● Process Sensor <small>Codex 프로세스 트리 관찰</small></span></div>}
        </div>
        <div className="card dashboard-card">
          <div className="dashboard-card-title">Codex 작업 공간</div>
          <div className="dashboard-card-desc">{isActive ? '현재 보호 세션에서 Codex가 작업 중입니다.' : 'Workspace와 정책을 선택해 보호 실행을 시작하세요.'}</div>
          <button type="button" className="dashboard-launch-btn" onClick={isActive ? () => setView('terminal') : openSettingsModal}><Icon name="terminal" size={20} /><span><b>{isActive ? 'Agent CLI 열기' : '보호 실행 설정'}</b><small>{isActive ? 'Codex 세션 연결됨' : preflight?.readiness_code ?? '환경 확인 중'}</small></span><strong>→</strong></button>
        </div>
      </div>
      <div className="card dashboard-activity-card">
        <div className="dashboard-activity-head"><div><div className="dashboard-card-title">최근 활동</div><div className="dashboard-card-desc">요청 · 실행 · 파일 변경을 하나의 보호 흐름으로 보여줍니다.</div></div>{isActive && <button type="button" className="activity-more" onClick={() => setView('audit')}>전체 활동 보기</button>}</div>
        <EventFeed runId={activeRunId} events={status?.events} evidenceChains={status?.evidence_chains} limit={5} />
      </div>
      {!isActive && <div className="card guardian-ready-brief"><div><div className="dashboard-card-title">보호 실행 준비 상태</div><div className="dashboard-card-desc">{preflight?.readiness_code === 'READY' ? 'Hook 연결이 검증되었습니다. 이제 안전한 작업을 시작할 수 있습니다.' : preflight?.next_step ?? 'Hook 연결과 환경을 확인하는 중입니다.'}</div></div><div className="guardian-ready-checks">{(preflight?.checks ?? []).map((check) => <span key={check.name} className={check.ok ? 'is-ok' : 'is-warn'}>● {check.label}</span>)}</div></div>}
    </div>
  )
}
