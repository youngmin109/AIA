import { useMemo, useState } from 'react'
import { usePreflight } from '../../hooks/usePreflight'
import { isRunActive, useRunList } from '../../hooks/useRunList'
import { useShellStore } from '../../state/shellStore'

const TABS = ['등록 현황', '연결 상태', '권한 범위', '승인 요청'] as const

export function AgentsView() {
  const [tab, setTab] = useState<(typeof TABS)[number]>('등록 현황')
  const { data: preflight } = usePreflight()
  const { data: runs } = useRunList()
  const { setView, openSettingsModal } = useShellStore()
  const codexAvailable = (preflight?.checks ?? []).some((check) => check.name.toLowerCase().includes('codex') && check.ok)
  const activeRuns = (runs ?? []).filter(isRunActive).length
  const lastRun = useMemo(() => (runs ?? [])[0], [runs])

  return (
    <div className="product-page">
      <header className="page-heading">
        <div><span className="page-eyebrow">AGENT GOVERNANCE</span><h2>보호 대상 에이전트</h2><p>등록된 런타임과 보호 연결 상태를 한곳에서 확인합니다.</p></div>
        <button type="button" className="primary-action" onClick={openSettingsModal}>새 보호 실행</button>
      </header>
      <nav className="subtabs" aria-label="에이전트 세부 메뉴">
        {TABS.map((item) => <button key={item} type="button" className={tab === item ? 'is-active' : ''} onClick={() => setTab(item)}>{item}</button>)}
      </nav>
      {tab === '등록 현황' ? (
        <>
          <div className="kpi-grid three">
            <article className="soft-card kpi-card"><span>지원 런타임</span><strong>1</strong><small>현재 Codex CLI 지원</small></article>
            <article className="soft-card kpi-card"><span>활성 보호 실행</span><strong>{activeRuns}</strong><small>실제 세션 기준</small></article>
            <article className="soft-card kpi-card"><span>연결 준비 상태</span><strong className={preflight?.readiness_code === 'READY' ? 'tone-good' : 'tone-warn'}>{preflight?.readiness_code === 'READY' ? '준비됨' : '확인 필요'}</strong><small>{preflight?.next_step ?? '환경을 확인하고 있습니다.'}</small></article>
          </div>
          <section className="soft-card data-section">
            <div className="section-title-row"><div><h3>에이전트 레지스트리</h3><p>엔진이 실제로 지원하는 런타임만 표시합니다.</p></div><span className="status-pill neutral">1개 항목</span></div>
            <div className="table-shell">
              <table className="product-table">
                <thead><tr><th>에이전트</th><th>제공자 / 유형</th><th>상태</th><th>보호 연결</th><th>활성 실행</th><th>최근 실행</th><th>작업</th></tr></thead>
                <tbody><tr><td><div className="agent-name"><span className="agent-orb">C</span><div><strong>Codex</strong><small>로컬 코딩 에이전트</small></div></div></td><td>OpenAI · CLI</td><td><span className={`status-pill ${codexAvailable ? 'good' : 'warning'}`}>{codexAvailable ? '사용 가능' : '확인 필요'}</span></td><td>{preflight?.readiness_code === 'READY' ? 'Hook 검증 완료' : 'Hook 설정 필요'}</td><td>{activeRuns}</td><td>{lastRun?.created_at ? new Date(lastRun.created_at).toLocaleString('ko-KR') : '기록 없음'}</td><td><button type="button" className="text-action" onClick={() => setView('terminal')}>열기</button></td></tr></tbody>
              </table>
            </div>
          </section>
        </>
      ) : (
        <section className="soft-card planned-panel"><span className="status-pill planned">연결 예정</span><h3>{tab}</h3><p>이 영역은 제품 정보 구조에 포함했지만 현재 Alpha 엔진에는 대응 API가 없습니다. 지원되지 않는 데이터를 임의로 표시하지 않습니다.</p></section>
      )}
    </div>
  )
}
