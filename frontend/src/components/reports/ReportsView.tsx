import { displayStatus, statusTone } from '../../api/display'
import { useMemo } from 'react'
import { useRunList } from '../../hooks/useRunList'
import { sessionDisplayName } from '../shell/sessionLabel'


export function ReportsView() {
  const { data: runs, isLoading } = useRunList()
  const metrics = useMemo(() => {
    const list = runs ?? []
    return {
      total: list.length,
      completed: list.filter((run) => run.status === 'COMPLETED').length,
      failed: list.filter((run) => run.status === 'FAILED').length,
      incidents: list.reduce((sum, run) => sum + Number(run.incident_count ?? 0), 0),
      verified: list.filter((run) => run.bundle_status === 'VALID').length,
    }
  }, [runs])

  return (
    <div className="product-page">
      <header className="page-heading"><div><p>보호 실행과 감사 번들에서 확인된 값만 집계합니다.</p></div><span className="status-pill neutral">로컬 데이터</span></header>
          <div className="kpi-grid five">
            <article className="soft-card kpi-card"><span>전체 실행</span><strong>{metrics.total}</strong><small>저장된 세션</small></article>
            <article className="soft-card kpi-card"><span>완료</span><strong className="tone-good">{metrics.completed}</strong><small>세션 종료 완료</small></article>
            <article className="soft-card kpi-card"><span>실패</span><strong className="tone-bad">{metrics.failed}</strong><small>재검토 대상</small></article>
            <article className="soft-card kpi-card"><span>정책 사건</span><strong className="tone-warn">{metrics.incidents}</strong><small>세션 누적</small></article>
            <article className="soft-card kpi-card"><span>기록 무결성</span><strong>{metrics.verified}</strong><small>감사 묶음 검증 완료</small></article>
          </div>
          <div className="report-grid">
            <section className="soft-card data-section"><div className="section-title-row"><div><h3>최근 실행 결과</h3><p>최근 보호 실행의 상태와 정책 사건을 보여줍니다.</p></div></div><div className="compact-list">{isLoading && !runs ? <p>불러오는 중입니다…</p> : (runs ?? []).slice(0, 6).map((run) => <div className="compact-list-row" key={run.session_id}><div><strong>{sessionDisplayName(run.workspace)}</strong><small>{run.workspace ?? '작업공간 확인 중'}</small></div><span className={`status-pill ${statusTone(run.status)}`}>{displayStatus(run.status)}</span><b>{run.incident_count ?? 0}건</b></div>)}{runs?.length === 0 && <p className="empty-copy">아직 보호 실행 기록이 없습니다.</p>}</div></section>
            <section className="soft-card data-section"><div className="section-title-row"><div><h3>보고서 범위</h3><p>현재 Alpha에서 신뢰할 수 있는 집계 범위입니다.</p></div></div><ul className="coverage-list"><li><span className="legend-dot mint" />세션 상태와 정책 사건 수</li><li><span className="legend-dot blue" />결과 번들 검증 상태</li><li><span className="legend-dot lavender" />작업공간별 실행 이력</li></ul><div className="validation-note">민감정보 분류와 장기 추세는 관련 수집 데이터가 추가된 뒤 제공됩니다.</div></section>
          </div>
    </div>
  )
}
