import { useMemo, useState } from 'react'
import { useRunList } from '../../hooks/useRunList'
import { sessionDisplayName } from '../shell/sessionLabel'

const TABS = ['보안 현황', '정책 위반', '민감 행위', '실행 결과', '감사 로그'] as const

export function ReportsView() {
  const [tab, setTab] = useState<(typeof TABS)[number]>('보안 현황')
  const { data: runs, isLoading } = useRunList()
  const metrics = useMemo(() => {
    const list = runs ?? []
    return {
      total: list.length,
      completed: list.filter((run) => run.status === 'COMPLETED').length,
      failed: list.filter((run) => ['FAILED', 'ABORTED'].includes(String(run.status))).length,
      incidents: list.reduce((sum, run) => sum + Number(run.incident_count ?? 0), 0),
      verified: list.filter((run) => String(run.bundle_status).toUpperCase().includes('VALID')).length,
    }
  }, [runs])

  return (
    <div className="product-page">
      <header className="page-heading"><div><span className="page-eyebrow">SECURITY REPORTING</span><h2>검증된 실행 결과</h2><p>보호 실행과 감사 번들에서 확인된 값만 집계합니다.</p></div><span className="status-pill neutral">로컬 데이터</span></header>
      <nav className="subtabs" aria-label="보고서 세부 메뉴">{TABS.map((item) => <button key={item} type="button" className={tab === item ? 'is-active' : ''} onClick={() => setTab(item)}>{item}</button>)}</nav>
      {tab === '보안 현황' ? (
        <>
          <div className="kpi-grid five">
            <article className="soft-card kpi-card"><span>전체 실행</span><strong>{metrics.total}</strong><small>저장된 세션</small></article>
            <article className="soft-card kpi-card"><span>완료</span><strong className="tone-good">{metrics.completed}</strong><small>완료 상태</small></article>
            <article className="soft-card kpi-card"><span>중단·실패</span><strong className="tone-bad">{metrics.failed}</strong><small>재검토 대상</small></article>
            <article className="soft-card kpi-card"><span>정책 사건</span><strong className="tone-warn">{metrics.incidents}</strong><small>세션 누적</small></article>
            <article className="soft-card kpi-card"><span>검증 번들</span><strong>{metrics.verified}</strong><small>VALID 상태</small></article>
          </div>
          <div className="report-grid">
            <section className="soft-card data-section"><div className="section-title-row"><div><h3>최근 실행 결과</h3><p>최근 보호 실행의 상태와 정책 사건을 보여줍니다.</p></div></div><div className="compact-list">{isLoading && !runs ? <p>불러오는 중입니다…</p> : (runs ?? []).slice(0, 6).map((run) => <div className="compact-list-row" key={run.session_id}><div><strong>{sessionDisplayName(run.workspace)}</strong><small>{run.workspace ?? '작업공간 확인 중'}</small></div><span className="status-pill neutral">{run.status ?? 'UNKNOWN'}</span><b>{run.incident_count ?? 0}건</b></div>)}{runs?.length === 0 && <p className="empty-copy">아직 보호 실행 기록이 없습니다.</p>}</div></section>
            <section className="soft-card data-section"><div className="section-title-row"><div><h3>보고서 범위</h3><p>현재 Alpha에서 신뢰할 수 있는 집계 범위입니다.</p></div></div><ul className="coverage-list"><li><span className="legend-dot mint" />세션 상태와 정책 사건 수</li><li><span className="legend-dot blue" />결과 번들 검증 상태</li><li><span className="legend-dot lavender" />Workspace별 실행 이력</li></ul><div className="validation-note">민감정보 분류와 조직 단위 추세는 수집 API가 추가된 뒤 제공됩니다.</div></section>
          </div>
        </>
      ) : <section className="soft-card planned-panel"><span className="status-pill planned">연결 예정</span><h3>{tab}</h3><p>현재 저장된 실행 기록으로 검증 가능한 세부 보고서부터 순차적으로 연결합니다.</p></section>}
    </div>
  )
}
