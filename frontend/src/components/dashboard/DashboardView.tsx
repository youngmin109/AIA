import { useMemo, useState } from 'react'
import { useShellStore } from '../../state/shellStore'
import { useRunStatus } from '../../hooks/useRunStatus'
import { usePreflight } from '../../hooks/usePreflight'
import { isRunActive, useRunList } from '../../hooks/useRunList'
import { GuardianHero } from './GuardianHero'
import { SensorHealthRow } from '../sensors/SensorHealthRow'
import { EventFeed } from '../sensors/EventFeed'
import { Icon } from '../common/Icon'
import { sessionDisplayName } from '../shell/sessionLabel'

const TABS = ['보호 현황', '보호 목표', 'AI 관측', '활동 탐색', '보고서'] as const

export function DashboardView() {
  const [tab, setTab] = useState<(typeof TABS)[number]>('보호 현황')
  const { activeRunId, setView, openSettingsModal, setActiveRun } = useShellStore()
  const { data: status } = useRunStatus(activeRunId, { enabled: Boolean(activeRunId) })
  const { data: preflight } = usePreflight()
  const { data: runs } = useRunList()
  const summary = status?.evidence_summary
  const isActive = Boolean(activeRunId)
  const healthyChecks = (preflight?.checks ?? []).filter((check) => check.ok).length
  const stats = useMemo(() => {
    const list = runs ?? []
    return {
      total: list.length,
      active: list.filter(isRunActive).length,
      incidents: list.reduce((sum, run) => sum + Number(run.incident_count ?? 0), 0),
      failed: list.filter((run) => ['FAILED', 'ABORTED'].includes(String(run.status))).length,
    }
  }, [runs])
  const metrics = [
    { label: '보호 대상 Agent', value: 1, hint: '현재 Codex CLI', tone: 'blue' },
    { label: '활성 보호 실행', value: stats.active, hint: `전체 ${stats.total}개 세션`, tone: 'mint' },
    { label: '정책 사건', value: stats.incidents, hint: '저장된 세션 누적', tone: 'rose' },
    { label: '중단·실패', value: stats.failed, hint: '재검토 필요', tone: 'lavender' },
  ]

  return (
    <div className="product-page observability-page">
      <nav className="observability-tabs" aria-label="대시보드 탭">{TABS.map((item) => <button key={item} type="button" className={tab === item ? 'is-active' : ''} onClick={() => { setTab(item); if (item === '보고서') setView('reports') }}>{item}</button>)}</nav>
      {tab === 'AI 관측' || tab === '보호 현황' ? <>
        <header className="page-heading dashboard-heading"><div><span className="page-eyebrow">RUNTIME ASSURANCE</span><h2>AI 작업을 투명하게 관찰합니다</h2><p>Agent 요청, 실제 프로세스, Workspace 변화를 하나의 보호 흐름으로 확인하세요.</p></div><button type="button" className="primary-action" onClick={isActive ? () => setView('terminal') : openSettingsModal}>{isActive ? '실행 열기' : '새 보호 실행'}</button></header>
        <div className="kpi-grid four">{metrics.map((metric) => <article key={metric.label} className={`soft-card kpi-card accent-${metric.tone}`}><span>{metric.label}</span><strong>{metric.value}</strong><small>{metric.hint}</small></article>)}</div>
        <div className="dashboard-showcase">
          <GuardianHero readiness={preflight ? `보호 조건 ${healthyChecks}개 정상` : '보호 조건 확인 중'} ready={preflight?.readiness_code === 'READY'} />
          <section className="soft-card live-observability"><div className="section-title-row"><div><h3>현재 관측 세션</h3><p>{isActive ? status?.session?.workspace ?? 'Workspace 확인 중' : '보호 실행을 시작하면 실시간 증거가 연결됩니다.'}</p></div><span className={`status-pill ${isActive ? 'good' : 'neutral'}`}>{isActive ? status?.session?.status ?? '연결 중' : '대기'}</span></div><div className="live-metric-row"><div><span>프로세스</span><b>{isActive ? summary?.process_observed ?? 0 : '—'}</b></div><div><span>Hook 이벤트</span><b>{isActive ? (summary?.pretool_events ?? 0) + (summary?.posttool_events ?? 0) : '—'}</b></div><div><span>파일 변경</span><b>{isActive ? summary?.filesystem_events ?? 0 : '—'}</b></div><div><span>정책 사건</span><b>{isActive ? status?.incident_count ?? 0 : '—'}</b></div></div>{isActive ? <SensorHealthRow sensorHealth={status?.sensor_health} evidenceSummary={summary} /> : <div className="sensor-explainer refined"><span>● PreTool Hook <small>실행 전 요청</small></span><span>● Process Sensor <small>프로세스 트리</small></span><span>● File Sensor <small>실제 파일 변화</small></span></div>}</section>
        </div>
        <div className="dashboard-lower-grid">
          <section className="soft-card data-section"><div className="section-title-row"><div><h3>최근 보호 실행</h3><p>실제 세션 상태와 사건 수를 표시합니다.</p></div><button type="button" className="text-action" onClick={() => setView('audit')}>전체 보기</button></div><div className="compact-list">{(runs ?? []).slice(0, 5).map((run) => <button type="button" className="compact-list-row is-button" key={run.session_id} onClick={() => { setActiveRun(run.session_id); setView(isRunActive(run) ? 'terminal' : 'audit') }}><div><strong>{sessionDisplayName(run.workspace)}</strong><small>{run.workspace ?? '작업공간 확인 중'}</small></div><span className="status-pill neutral">{run.status ?? 'UNKNOWN'}</span><b>{run.incident_count ?? 0}건</b></button>)}{runs?.length === 0 && <p className="empty-copy">아직 보호 실행 기록이 없습니다.</p>}</div></section>
          <section className="soft-card data-section"><div className="section-title-row"><div><h3>최근 감사 이벤트</h3><p>현재 선택한 세션의 정규화된 활동입니다.</p></div>{isActive && <button type="button" className="text-action" onClick={() => setView('audit')}>증거 열기</button>}</div><EventFeed runId={activeRunId} events={status?.events} evidenceChains={status?.evidence_chains} limit={5} /></section>
        </div>
        <section className="soft-card readiness-strip"><div><Icon name="shield" size={20} /><div><b>{preflight?.readiness_code === 'READY' ? '보호 실행 준비 완료' : '보호 연결 확인 필요'}</b><span>{preflight?.next_step ?? 'Hook과 로컬 실행 환경을 확인하고 있습니다.'}</span></div></div><div className="check-chip-row">{(preflight?.checks ?? []).map((check) => <span key={check.name} className={`check-chip ${check.ok ? 'ok' : 'warn'}`}>{check.ok ? '✓' : '!'} {check.label}</span>)}</div></section>
      </> : tab === '보호 목표' ? <section className="soft-card planned-panel"><span className="status-pill planned">제품 로드맵</span><h3>보호 목표</h3><p>실행 전 차단, 실행 중 프로세스 가시화, 작업 후 복구·무결성 검증을 핵심 목표로 추적합니다.</p></section> : <section className="soft-card planned-panel"><span className="status-pill planned">연결 예정</span><h3>{tab}</h3><p>현재 엔진에서 검증 가능한 데이터부터 연결합니다. 수집되지 않은 지표를 임의 값으로 표시하지 않습니다.</p></section>}
    </div>
  )
}
