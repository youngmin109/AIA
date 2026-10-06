import { Button } from '../common/Button'
import { StatusPill } from '../common/Badge'
import { displayStatus, isSessionRunning, readinessNextStep, checkLabel } from '../../api/display'
import { WorkspaceActivity } from './WorkspaceActivity'
import { useShellStore } from '../../state/shellStore'
import { useRunStatus } from '../../hooks/useRunStatus'
import { usePreflight } from '../../hooks/usePreflight'
import { isRunActive, useRunList } from '../../hooks/useRunList'
import { GuardianHero } from './GuardianHero'
import { SensorHealthRow } from '../sensors/SensorHealthRow'
import { EventFeed } from '../sensors/EventFeed'
import { Icon } from '../common/Icon'
import { sessionDisplayName } from '../shell/sessionLabel'


export function DashboardView() {
  const { activeRunId, setView, openNewRun, setActiveRun } = useShellStore()
  const { data: status, error, updatedAt } = useRunStatus(activeRunId, { enabled: Boolean(activeRunId) })
  const { data: preflight } = usePreflight()
  const { data: runs } = useRunList()
  const summary = status?.evidence_summary
  const isActive = isSessionRunning(status?.session?.status, status?.runtime_reconciliation?.orphaned)
  const selected = Boolean(activeRunId)
  const activity = status?.activity
  const healthyChecks = (preflight?.checks ?? []).filter((check) => check.ok).length
  const metrics = [
    { label: '현재 생존 프로세스', value: isActive && !error ? activity?.current_alive_count ?? '—' : '—', hint: isActive ? '등록된 PID·생성 시각으로 확인' : '실행 중인 세션에서 확인', tone: 'blue' },
    { label: '변경 관찰 파일', value: activity?.unique_file_count ?? '—', hint: '같은 경로의 반복 변경은 한 개', tone: 'mint' },
    { label: '파일 변경 이벤트', value: summary?.filesystem_events ?? '—', hint: '생성·수정·삭제·이동 누적', tone: 'lavender' },
    { label: '이번 세션 정책 사건', value: status?.incident_count ?? '—', hint: '판정과 실제 조치 결과는 별도', tone: 'rose' },
  ]

  return (
    <div className="product-page observability-page">
        <header className="page-heading dashboard-heading"><div><p>에이전트 요청, 실제 프로세스, 작업공간 변화를 하나의 보호 흐름으로 확인하세요.</p></div><Button variant="primary" onClick={isActive ? () => setView('work') : openNewRun}>{isActive ? '실행 열기' : '새 보호 실행'}</Button></header>
        <div className="kpi-grid four">{metrics.map((metric) => <article key={metric.label} className={`soft-card kpi-card accent-${metric.tone}`}><span>{metric.label}</span><strong>{metric.value}</strong><small>{metric.hint}</small></article>)}</div>
        {error && <div className="validation-banner warning" role="alert">최신 상태를 가져오지 못했습니다. 정상 보호 상태로 해석하지 마세요.</div>}
        {updatedAt && <p className="snapshot-time">마지막 확인 {new Date(updatedAt).toLocaleTimeString('ko-KR')}{!isActive && selected ? ' · 종료된 실행 기록' : ''}</p>}
        <div className="dashboard-showcase">
          <GuardianHero readiness={preflight ? `보호 조건 ${healthyChecks}개 정상` : '보호 조건 확인 중'} ready={preflight?.readiness_code === 'READY'} />
          <section className="soft-card live-observability"><div className="section-title-row"><div><h3>{isActive ? '현재 관측 세션' : selected ? '선택한 실행 기록' : '관측 대기'}</h3><p>{selected ? status?.session?.workspace ?? '작업공간 확인 중' : '보호 실행을 시작하면 실시간 증거가 연결됩니다.'}</p></div><StatusPill tone={isActive && !error ? 'good' : 'neutral'}>{selected ? displayStatus(status?.session?.status) : '대기'}</StatusPill></div><div className="live-metric-row"><div><span>누적 프로세스 관찰</span><b>{selected ? activity?.process_identity_count ?? '—' : '—'}</b></div><div><span>실행 전·후 연결 이벤트</span><b>{selected && summary ? (summary.pretool_events ?? 0) + (summary.posttool_events ?? 0) : '—'}</b></div><div><span>파일 변경 이벤트</span><b>{selected ? summary?.filesystem_events ?? '—' : '—'}</b></div><div><span>정책 사건</span><b>{selected ? status?.incident_count ?? '—' : '—'}</b></div></div>{selected ? <SensorHealthRow sensorHealth={status?.sensor_health} evidenceSummary={summary} /> : <div className="sensor-explainer refined"><span>● 실행 전 연결 <small>실행 전 요청</small></span><span>● 프로세스 센서 <small>프로세스 트리</small></span><span>● 파일 센서 <small>실제 파일 변화</small></span></div>}</section>
        </div>
        <WorkspaceActivity status={status} />
        <div className="dashboard-lower-grid">
          <section className="soft-card data-section"><div className="section-title-row"><div><h3>최근 보호 실행</h3><p>실제 세션 상태와 사건 수를 표시합니다.</p></div><Button variant="text" onClick={() => setView('history')}>전체 보기</Button></div><div className="compact-list">{(runs ?? []).slice(0, 5).map((run) => <button type="button" className="compact-list-row is-button" key={run.session_id} onClick={() => { setActiveRun(run.session_id); setView(isRunActive(run) ? 'work' : 'history') }}><div><strong>{sessionDisplayName(run.workspace)}</strong><small>{run.workspace ?? '작업공간 확인 중'}</small></div><StatusPill tone="neutral">{displayStatus(run.status)}</StatusPill><b>{run.incident_count ?? 0}건</b></button>)}{runs?.length === 0 && <p className="empty-copy">아직 보호 실행 기록이 없습니다.</p>}</div></section>
          <section className="soft-card data-section"><div className="section-title-row"><div><h3>최근 감사 이벤트</h3><p>현재 선택한 세션의 정규화된 활동입니다.</p></div>{isActive && <Button variant="text" onClick={() => setView('history')}>증거 열기</Button>}</div><EventFeed runId={activeRunId} events={status?.events} evidenceChains={status?.evidence_chains} limit={5} /></section>
        </div>
        <section className="soft-card readiness-strip"><div><Icon name="shield" size={20} /><div><b>{preflight?.readiness_code === 'READY' ? '보호 실행 준비 완료' : '보호 연결 확인 필요'}</b><span>{preflight ? readinessNextStep(preflight.readiness_code) : '실행 전 연결과 로컬 환경을 확인하고 있습니다.'}</span></div></div><div className="check-chip-row">{(preflight?.checks ?? []).map((check) => <span key={check.name} className={`check-chip ${check.ok ? 'ok' : 'warn'}`} title={check.detail}>{check.ok ? '✓' : '!'} {checkLabel(check.label)}</span>)}</div></section>
    </div>
  )
}
