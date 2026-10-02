import { useEffect, useState } from 'react'
import { listProfiles, type PolicyProfile } from '../../api/endpoints'
import { readDefaultPolicyProfile, writeDefaultPolicyProfile } from './policyStorage'

type PolicyTab = '정책 현황' | '템플릿' | '실행 범위' | '런타임 보호' | '데이터 보호' | '탐지 및 대응' | '감사 기록'

const TABS: PolicyTab[] = ['정책 현황', '템플릿', '실행 범위', '런타임 보호', '데이터 보호', '탐지 및 대응', '감사 기록']

type SupportStatus = '지원' | '부분 지원'

// Only behaviour the engine performs today is listed here. Planned work stays
// in the docs so the console never implies protection that does not exist.
const CATEGORY_CONTENT: Partial<Record<PolicyTab, { summary: string; items: Array<{ title: string; description: string; status: SupportStatus }> }>> = {
  '실행 범위': { summary: '보호 실행이 어떤 Workspace와 도구 요청을 대상으로 하는지 보여 줍니다.', items: [
    { title: 'Workspace 범위', description: '보호 실행 시작 시 지정한 Workspace를 관찰과 복구의 기준으로 사용합니다.', status: '지원' },
    { title: 'Workspace 밖 쓰기', description: 'Codex 샌드박스(workspace-write)가 제한합니다. AIA 정책이 직접 통제하지는 않습니다.', status: '부분 지원' },
    { title: 'Tool·명령 범위', description: 'Agent가 요청하는 Tool과 위험 명령을 실행 전에 평가합니다.', status: '부분 지원' },
    { title: '사용자 확인', description: '지원 범위 밖 도구는 사용자에게 확인합니다. 정책상 금지된 동작은 허용할 수 없습니다.', status: '부분 지원' },
  ] },
  '런타임 보호': { summary: 'Protected Run의 준비·관찰·복구 조건입니다.', items: [
    { title: '정책 고정과 Workspace Lease', description: '실행 중 정책 변경과 같은 Workspace의 중복 보호 실행을 막습니다.', status: '지원' },
    { title: 'Safe Checkpoint', description: '실행 전 파일 존재 여부와 SHA-256 Manifest를 복구 기준점으로 만듭니다.', status: '지원' },
    { title: 'Process Tree 관찰', description: '등록된 Agent Root와 자식 프로세스를 관찰하고, 사용자가 중지하면 그 트리만 종료합니다. 정책 위반에 따른 실제 Codex 자동 종료는 아직 검증하지 않았습니다.', status: '부분 지원' },
  ] },
  '데이터 보호': { summary: '민감 파일과 증거가 어떻게 다뤄지는지 보여 줍니다.', items: [
    { title: '비밀정보 경로 보호', description: '프로필별 .env 등 민감 경로 규칙을 평가합니다.', status: '지원' },
    { title: '증거 표시 제한', description: '화면에는 명령 원문과 비밀값을 표시하지 않고, 진단 묶음(support-bundle)은 민감정보를 제거해 만듭니다.', status: '지원' },
  ] },
  '탐지 및 대응': { summary: '서로 다른 센서 증거를 연결해 정책 판단과 대응 수준을 정합니다.', items: [
    { title: 'Evidence 정규화·귀속', description: 'Hook·Process·File Evidence를 하나의 행위로 연결합니다.', status: '지원' },
    { title: 'Allow · Contain · Refuse', description: '정책·귀속·센서 상태에 따라 Gate가 대응을 정합니다.', status: '지원' },
    { title: '복구·무결성 검증', description: 'Checkpoint 복원 후 경로·SHA-256 결과를 확인합니다.', status: '지원' },
  ] },
  '감사 기록': { summary: 'Agent의 증거와 정책 판단을 검증 가능한 결과로 보존합니다.', items: [
    { title: '감사 기록과 Result Bundle', description: '세션별 Evidence·판정·조치·무결성 결과를 묶어 확정합니다.', status: '지원' },
    { title: 'Bundle 무결성 검증', description: '저장된 결과 번들의 위변조 여부를 다시 검증합니다.', status: '지원' },
  ] },
}

export function PolicyView() {
  const [profiles, setProfiles] = useState<PolicyProfile[]>([])
  const [selected, setSelected] = useState<string | null>(null)
  const [tab, setTab] = useState<PolicyTab>('정책 현황')
  const [query, setQuery] = useState('')
  const [notice, setNotice] = useState('')

  useEffect(() => {
    listProfiles().then((list) => {
      const available = list.filter((profile) => profile.value !== 'CUSTOM')
      setProfiles(available)
      const saved = readDefaultPolicyProfile()
      setSelected(saved && available.some((profile) => profile.value === saved) ? saved : available[0]?.value ?? null)
    }).catch(() => setProfiles([]))
  }, [])

  const activeProfile = profiles.find((profile) => profile.value === selected)

  function choose(profile: PolicyProfile) {
    setSelected(profile.value)
    writeDefaultPolicyProfile(profile.value)
    setNotice(`${profile.display_name}을(를) 이 브라우저의 다음 실행 기본값으로 저장했습니다.`)
  }

  const content = CATEGORY_CONTENT[tab]

  return (
    <div className="product-page policy-console">
      <header className="page-heading"><div><p>내 Agent에 적용할 보호 수준을 고르고, 엔진이 실제로 하는 일을 확인합니다.</p></div><span className="status-pill good">엔진 프로필 연결됨</span></header>
      <div className="policy-workspace">
        <aside className="policy-nav">
          <label className="policy-search"><span>⌕</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="정책 메뉴 검색" /></label>
          {TABS.filter((item) => item.includes(query.trim())).map((item) => <button key={item} type="button" className={tab === item ? 'is-active' : ''} onClick={() => { setTab(item); setNotice('') }}>{item}<span>›</span></button>)}
        </aside>
        <main className="policy-content">
          {notice && <div className="validation-banner good">✓ {notice}</div>}
          {tab === '정책 현황' && <PolicyOverview activeProfile={activeProfile} profiles={profiles} onOpenTemplates={() => setTab('템플릿')} />}
          {tab === '템플릿' && <PolicyTemplates profiles={profiles} selected={selected} choose={choose} />}
          {content && <PolicyCategory title={tab} summary={content.summary} items={content.items} />}
        </main>
      </div>
    </div>
  )
}

function PolicyOverview({ activeProfile, profiles, onOpenTemplates }: { activeProfile?: PolicyProfile; profiles: PolicyProfile[]; onOpenTemplates: () => void }) {
  return <div className="policy-panel-stack"><section className="policy-hero soft-card"><div><h3>{activeProfile?.display_name ?? '불러오는 중'}</h3><p>{activeProfile?.description ?? 'AIA 엔진에서 정책 프로필을 확인하고 있습니다.'}</p></div><span className="status-pill good">다음 실행 기본값</span></section><div className="kpi-grid four"><article className="soft-card kpi-card"><span>사용 가능한 템플릿</span><strong>{profiles.length}</strong><small>엔진에서 확인됨</small></article><article className="soft-card kpi-card"><span>현재 정책</span><strong>내장</strong><small>AIA 기본 프로필</small></article><article className="soft-card kpi-card"><span>실행 중 변경</span><strong>고정</strong><small>Active Policy Freeze</small></article><article className="soft-card kpi-card"><span>직접 설정</span><strong>CLI</strong><small>--policy &lt;json&gt;</small></article></div><section className="soft-card data-section"><div className="section-title-row"><div><h3>정책 작업</h3><p>내 작업 방식에 맞는 보호 수준을 선택합니다.</p></div></div><div className="policy-quick-actions"><button type="button" onClick={onOpenTemplates}><b>템플릿 선택</b><span>엔진이 지원하는 프로필을 다음 실행 기본값으로 지정</span></button></div><div className="validation-note">직접 작성한 정책은 Strict Validation을 통과한 JSON을 실행할 때 <code className="mono">--policy &lt;json&gt;</code>으로 지정합니다.</div></section></div>
}

function PolicyTemplates({ profiles, selected, choose }: { profiles: PolicyProfile[]; selected: string | null; choose: (profile: PolicyProfile) => void }) {
  return <section><div className="policy-section-heading"><div><h3>정책 템플릿</h3><p>아래 카드는 AIA 엔진이 제공하는 실제 프로필이며, 설명도 서버의 정책 정의를 사용합니다. 선택은 이 브라우저의 다음 보호 실행 기본값으로 저장되고, 보호 세팅 창에서 실행마다 다시 고를 수 있습니다.</p></div></div><div className="policy-template-grid">{profiles.map((profile) => <article key={profile.value} className={`soft-card policy-template-card${selected === profile.value ? ' is-selected' : ''}`}><div className="template-card-top"><span className="template-icon">{profile.display_name.slice(0, 1)}</span><span className={`status-pill ${selected === profile.value ? 'good' : 'neutral'}`}>{selected === profile.value ? '현재 기본값' : '사용 가능'}</span></div><h4>{profile.display_name}</h4><p>{profile.description ?? '설명이 제공되지 않았습니다.'}</p><dl><div><dt>적용 범위</dt><dd>다음 보호 실행</dd></div><div><dt>정책 고정</dt><dd>실행 중 변경 불가</dd></div></dl><button type="button" className="secondary-action" disabled={selected === profile.value} onClick={() => choose(profile)}>{selected === profile.value ? '선택됨' : '기본값으로 선택'}</button></article>)}{profiles.length === 0 && <p className="empty-copy">정책 프로필을 불러오지 못했습니다.</p>}</div></section>
}

function PolicyCategory({ title, summary, items }: { title: string; summary: string; items: Array<{ title: string; description: string; status: SupportStatus }> }) {
  return <section><div className="policy-section-heading"><div><h3>{title}</h3><p>{summary}</p></div><span className="status-pill neutral">{items.length}개 영역</span></div><div className="policy-setting-list">{items.map((item) => <article key={item.title} className="soft-card policy-setting-row"><div><h4>{item.title}</h4><p>{item.description}</p></div><span className={`status-pill ${item.status === '지원' ? 'good' : 'warning'}`}>{item.status}</span></article>)}</div><div className="validation-note">이 목록에는 현재 엔진이 실제로 수행하는 동작만 표시합니다.</div></section>
}
