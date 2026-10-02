import { useEffect, useMemo, useState } from 'react'
import { listProfiles, type PolicyProfile } from '../../api/endpoints'
import { readDefaultPolicyProfile, writeDefaultPolicyProfile } from './policyStorage'

type PolicyTab = '개요' | '템플릿' | '접근 제어' | '에이전트 설정' | '런타임 제어' | '데이터 보호' | '탐지 및 대응' | '감사 및 보존' | '수명주기' | '맞춤 설정'

const TABS: PolicyTab[] = ['개요', '템플릿', '접근 제어', '에이전트 설정', '런타임 제어', '데이터 보호', '탐지 및 대응', '감사 및 보존', '수명주기', '맞춤 설정']

const CATEGORY_CONTENT: Partial<Record<PolicyTab, { summary: string; items: Array<{ title: string; description: string; status: '지원' | '부분 지원' | '계획' }> }>> = {
  '접근 제어': { summary: 'Agent·Workspace·Tool의 실행 범위와 승인 책임을 정의합니다.', items: [
    { title: 'Workspace 접근 범위', description: '보호 실행 시작 시 지정한 Workspace를 경계로 사용합니다.', status: '지원' },
    { title: '역할 기반 접근 제어', description: '운영자·관리자·감사자·일반 사용자 권한 모델입니다.', status: '계획' },
    { title: 'Tool·Connector 허용 목록', description: 'Agent가 호출할 수 있는 외부 도구 범위를 관리합니다.', status: '부분 지원' },
    { title: '고위험 실행 승인', description: '지원 범위 밖 도구는 사용자 확인을 요청합니다. 정책상 금지된 동작은 승인할 수 없습니다.', status: '부분 지원' },
  ] },
  '에이전트 설정': { summary: 'Agent Adapter와 실행 권한 프로파일을 런타임별로 관리합니다.', items: [
    { title: 'Codex Adapter · Hook', description: 'PreTool 이벤트를 AIA의 공통 Evidence 형식으로 전달합니다.', status: '지원' },
    { title: 'Agent capability profile', description: '파일·Shell·네트워크·외부 Connector 권한을 정의합니다.', status: '부분 지원' },
    { title: '추가 Agent Runtime', description: 'Claude Code 등 다른 런타임용 Adapter 확장 지점입니다.', status: '계획' },
  ] },
  '런타임 제어': { summary: 'Protected Run의 준비·관찰·집행·복구 조건을 관리합니다.', items: [
    { title: '정책 고정과 Workspace Lease', description: '실행 중 정책 변경과 동일 Workspace 중복 보호 세션을 방지합니다.', status: '지원' },
    { title: 'Safe Checkpoint', description: '실행 전 파일 존재 여부와 SHA-256 Manifest를 복구 기준점으로 만듭니다.', status: '지원' },
    { title: 'Process Tree 통제', description: '등록된 Agent Root와 자식 프로세스만 관찰·종료합니다.', status: '지원' },
    { title: '실행 시간·병렬 수 제한', description: '조직 단위 실행 한도와 세션 제한을 관리합니다.', status: '계획' },
  ] },
  '데이터 보호': { summary: '민감 파일·자격증명·Workspace 외부 유출 위험을 통제합니다.', items: [
    { title: '비밀정보 경로 보호', description: '프로필별 .env 등 민감 경로 읽기 규칙을 평가합니다.', status: '지원' },
    { title: 'Workspace 외부 접근', description: '보호 경계를 벗어난 경로 접근을 정책으로 통제합니다.', status: '지원' },
    { title: 'Evidence 마스킹', description: '결과와 지원 자료에서 민감정보를 제거하는 확장 영역입니다.', status: '부분 지원' },
    { title: 'PII·소스코드 분류', description: '콘텐츠 기반 민감도 분류와 Oversharing 탐지입니다.', status: '계획' },
  ] },
  '탐지 및 대응': { summary: '서로 다른 센서 증거를 연결해 정책 판단과 대응 수준을 결정합니다.', items: [
    { title: 'Evidence 정규화·귀속', description: 'Hook·Process·File Evidence를 Canonical Action으로 연결합니다.', status: '지원' },
    { title: 'Allow · Contain · Refuse', description: '정책·귀속·센서 상태에 따라 Gate가 권한을 결정합니다.', status: '지원' },
    { title: '복구·무결성 검증', description: 'Checkpoint 복원 후 경로·SHA-256 결과를 확인합니다.', status: '지원' },
    { title: '운영자 검토 큐·알림', description: '조직용 검토 워크플로와 외부 알림 채널입니다.', status: '계획' },
  ] },
  '감사 및 보존': { summary: '증거와 정책 판단을 검증 가능한 결과로 보존합니다.', items: [
    { title: '감사 기록과 Result Bundle', description: '세션별 Evidence·판정·집행·무결성 결과를 묶어 확정합니다.', status: '지원' },
    { title: 'Bundle 무결성 검증', description: '저장된 결과 번들의 위변조 여부를 다시 검증합니다.', status: '지원' },
    { title: '보존 기간·자동 삭제', description: '조직 보존 정책과 데이터 수명주기입니다.', status: '계획' },
    { title: 'eDiscovery 내보내기', description: '감사·컴플라이언스 시스템 연계를 위한 표준 내보내기입니다.', status: '계획' },
  ] },
  '수명주기': { summary: '정책의 작성·검토·게시·보관 단계를 관리합니다.', items: [
    { title: '로컬 기본 프로필', description: '다음 보호 실행에 사용할 기본 프로필을 이 기기에 저장합니다.', status: '지원' },
    { title: 'Draft · Review · Publish', description: '조직 정책의 승인과 게시 상태를 관리합니다.', status: '계획' },
    { title: '정책 버전·변경 감사', description: '정책 변경 diff와 승인 이력을 추적합니다.', status: '계획' },
    { title: '신규 Agent 자동 적용', description: '등록 시 기본 템플릿을 자동 배정합니다.', status: '계획' },
  ] },
}

interface CustomDraft {
  base: string
  checkpoint: boolean
  freezePolicy: boolean
  blockOutsideWorkspace: boolean
  childProcess: 'allow-listed' | 'observe' | 'block'
  sensitiveFiles: 'block' | 'warn' | 'audit'
  unknownTool: 'approval' | 'block'
  recovery: 'manual' | 'automatic' | 'disabled'
}

const DEFAULT_DRAFT: CustomDraft = { base: 'PROTECTED_DEVELOPMENT', checkpoint: true, freezePolicy: true, blockOutsideWorkspace: true, childProcess: 'allow-listed', sensitiveFiles: 'block', unknownTool: 'approval', recovery: 'manual' }
const DRAFT_KEY = 'aia.policy.customDraft.v1'

function loadDraft(): CustomDraft {
  try { return { ...DEFAULT_DRAFT, ...JSON.parse(window.localStorage.getItem(DRAFT_KEY) ?? '{}') } }
  catch { return DEFAULT_DRAFT }
}

export function PolicyView() {
  const [profiles, setProfiles] = useState<PolicyProfile[]>([])
  const [selected, setSelected] = useState<string | null>(null)
  const [tab, setTab] = useState<PolicyTab>('개요')
  const [query, setQuery] = useState('')
  const [draft, setDraft] = useState<CustomDraft>(loadDraft)
  const [savedDraft, setSavedDraft] = useState<CustomDraft>(loadDraft)
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
  const dirty = JSON.stringify(draft) !== JSON.stringify(savedDraft)
  const validation = useMemo(() => {
    const issues: string[] = []
    if (draft.recovery !== 'disabled' && !draft.checkpoint) issues.push('복구를 사용하려면 Safe Checkpoint가 필요합니다.')
    if (!draft.freezePolicy) issues.push('실행 중 정책 변경 가능성이 있어 검증 재현성이 낮아집니다.')
    if (!draft.blockOutsideWorkspace) issues.push('Workspace 외부 접근이 허용되어 보호 경계가 약해집니다.')
    return issues
  }, [draft])

  function choose(profile: PolicyProfile) {
    setSelected(profile.value)
    writeDefaultPolicyProfile(profile.value)
    setNotice(`${profile.display_name}을(를) 다음 실행 기본값으로 저장했습니다.`)
  }

  function saveCustomDraft() {
    window.localStorage.setItem(DRAFT_KEY, JSON.stringify(draft))
    setSavedDraft(draft)
    setNotice('맞춤 정책 초안을 이 기기에 저장했습니다. 아직 AIA 엔진에 게시되지는 않았습니다.')
  }

  const content = CATEGORY_CONTENT[tab]

  return (
    <div className="product-page policy-console">
      <header className="page-heading"><div><span className="page-eyebrow">POLICY GOVERNANCE</span><h2>정책 관리</h2><p>실제 엔진 프로필과 향후 조직 정책 구조를 구분해 관리합니다.</p></div><div className="policy-header-actions"><span className="status-pill good">엔진 프로필 연결됨</span><button type="button" className="secondary-action" onClick={() => setTab('맞춤 설정')}>맞춤 정책 만들기</button></div></header>
      <div className="policy-workspace">
        <aside className="policy-nav">
          <label className="policy-search"><span>⌕</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="정책 메뉴 검색" /></label>
          {TABS.filter((item) => item.includes(query.trim())).map((item) => <button key={item} type="button" className={tab === item ? 'is-active' : ''} onClick={() => { setTab(item); setNotice('') }}>{item}<span>›</span></button>)}
        </aside>
        <main className="policy-content">
          {notice && <div className="validation-banner good">✓ {notice}</div>}
          {tab === '개요' && <PolicyOverview activeProfile={activeProfile} profiles={profiles} onOpenTemplates={() => setTab('템플릿')} onOpenCustom={() => setTab('맞춤 설정')} />}
          {tab === '템플릿' && <PolicyTemplates profiles={profiles} selected={selected} choose={choose} />}
          {content && <PolicyCategory title={tab} summary={content.summary} items={content.items} />}
          {tab === '맞춤 설정' && <CustomPolicy draft={draft} setDraft={setDraft} dirty={dirty} validation={validation} save={saveCustomDraft} reset={() => { setDraft(DEFAULT_DRAFT); setNotice('템플릿 기본값으로 되돌렸습니다. 저장 전까지는 초안에만 반영됩니다.') }} test={() => setNotice(validation.length ? `검증 결과: ${validation.length}개의 확인 항목이 있습니다.` : '구성 검증을 통과했습니다. 실제 실행 시뮬레이션 API는 아직 연결되지 않았습니다.')} />}
        </main>
      </div>
    </div>
  )
}

function PolicyOverview({ activeProfile, profiles, onOpenTemplates, onOpenCustom }: { activeProfile?: PolicyProfile; profiles: PolicyProfile[]; onOpenTemplates: () => void; onOpenCustom: () => void }) {
  return <div className="policy-panel-stack"><section className="policy-hero soft-card"><div><span className="page-eyebrow">ACTIVE PROFILE</span><h3>{activeProfile?.display_name ?? '불러오는 중'}</h3><p>{activeProfile?.description ?? 'AIA 엔진에서 정책 프로필을 확인하고 있습니다.'}</p></div><span className="status-pill good">다음 실행 기본값</span></section><div className="kpi-grid four"><article className="soft-card kpi-card"><span>엔진 템플릿</span><strong>{profiles.length}</strong><small>API에서 확인됨</small></article><article className="soft-card kpi-card"><span>정책 상태</span><strong>게시됨</strong><small>내장 프로필</small></article><article className="soft-card kpi-card"><span>실행 중 변경</span><strong>고정</strong><small>Active Policy Freeze</small></article><article className="soft-card kpi-card"><span>맞춤 초안</span><strong>로컬</strong><small>엔진 연결 전</small></article></div><section className="soft-card data-section"><div className="section-title-row"><div><h3>정책 작업</h3><p>현재 지원 범위를 명확히 구분합니다.</p></div></div><div className="policy-quick-actions"><button type="button" onClick={onOpenTemplates}><b>템플릿 선택</b><span>엔진이 지원하는 프로필을 다음 실행 기본값으로 지정</span></button><button type="button" onClick={onOpenCustom}><b>맞춤 초안 설계</b><span>세부 옵션을 구성하고 충돌 여부를 미리 확인</span></button></div></section></div>
}

function PolicyTemplates({ profiles, selected, choose }: { profiles: PolicyProfile[]; selected: string | null; choose: (profile: PolicyProfile) => void }) {
  return <section><div className="policy-section-heading"><div><span className="page-eyebrow">TEMPLATES</span><h3>정책 템플릿</h3><p>아래 카드는 실제 AIA 엔진이 제공한 프로필입니다. 설명 역시 서버의 정책 정의를 사용합니다.</p></div></div><div className="policy-template-grid">{profiles.map((profile) => <article key={profile.value} className={`soft-card policy-template-card${selected === profile.value ? ' is-selected' : ''}`}><div className="template-card-top"><span className="template-icon">{profile.display_name.slice(0, 1)}</span><span className={`status-pill ${selected === profile.value ? 'good' : 'neutral'}`}>{selected === profile.value ? '현재 기본값' : '사용 가능'}</span></div><h4>{profile.display_name}</h4><p>{profile.description ?? '설명이 제공되지 않았습니다.'}</p><dl><div><dt>적용 범위</dt><dd>다음 보호 실행</dd></div><div><dt>정책 고정</dt><dd>실행 중 변경 불가</dd></div></dl><button type="button" className="secondary-action" disabled={selected === profile.value} onClick={() => choose(profile)}>{selected === profile.value ? '선택됨' : '기본값으로 선택'}</button></article>)}{profiles.length === 0 && <p className="empty-copy">정책 프로필을 불러오지 못했습니다.</p>}</div></section>
}

function PolicyCategory({ title, summary, items }: { title: string; summary: string; items: Array<{ title: string; description: string; status: '지원' | '부분 지원' | '계획' }> }) {
  return <section><div className="policy-section-heading"><div><span className="page-eyebrow">POLICY CATEGORY</span><h3>{title}</h3><p>{summary}</p></div><span className="status-pill neutral">{items.length}개 영역</span></div><div className="policy-setting-list">{items.map((item) => <article key={item.title} className="soft-card policy-setting-row"><div><h4>{item.title}</h4><p>{item.description}</p></div><span className={`status-pill ${item.status === '지원' ? 'good' : item.status === '부분 지원' ? 'warning' : 'planned'}`}>{item.status}</span></article>)}</div><div className="validation-note">‘계획’으로 표시된 항목은 UI 정보 구조만 정의된 상태이며 현재 보호 판단에 영향을 주지 않습니다.</div></section>
}

function CustomPolicy({ draft, setDraft, dirty, validation, save, reset, test }: { draft: CustomDraft; setDraft: (next: CustomDraft) => void; dirty: boolean; validation: string[]; save: () => void; reset: () => void; test: () => void }) {
  function patch<K extends keyof CustomDraft>(key: K, value: CustomDraft[K]) { setDraft({ ...draft, [key]: value }) }
  return <section><div className="policy-section-heading"><div><span className="page-eyebrow">CUSTOM MODE</span><h3>맞춤 정책 초안</h3><p>기본 템플릿에서 시작해 세부 동작을 조정합니다. 현재 Alpha에서는 로컬 초안과 검증 UI만 제공하며 엔진 게시·실행 시뮬레이션은 연결 예정입니다.</p></div><span className={`status-pill ${dirty ? 'warning' : 'neutral'}`}>{dirty ? '저장하지 않은 변경' : '초안 저장됨'}</span></div>{validation.length > 0 ? <div className="validation-banner warning"><b>구성 확인 필요</b>{validation.map((issue) => <span key={issue}>• {issue}</span>)}</div> : <div className="validation-banner good">✓ 현재 구성에서 명백한 충돌을 찾지 못했습니다.</div>}<div className="custom-policy-grid"><div className="custom-form"><section className="soft-card settings-block"><h4>기본 템플릿</h4><label>시작 프로필<select value={draft.base} onChange={(event) => patch('base', event.target.value)}><option value="PROTECTED_DEVELOPMENT">표준 보호</option><option value="BASIC_OBSERVATION">협업 개발</option><option value="CONSERVATIVE_SECURITY">변경 통제 강화</option><option value="FREE_OBSERVATION">관찰 전용</option></select></label></section><section className="soft-card settings-block"><h4>실행 보호</h4><ToggleRow label="Safe Checkpoint 생성" detail="복구 기준점을 실행 전에 만듭니다." checked={draft.checkpoint} onChange={(value) => patch('checkpoint', value)} /><ToggleRow label="Active Policy Freeze" detail="세션 동안 적용 정책을 고정합니다." checked={draft.freezePolicy} onChange={(value) => patch('freezePolicy', value)} /><ToggleRow label="Workspace 외부 접근 차단" detail="선택한 작업공간 밖의 변경을 통제합니다." checked={draft.blockOutsideWorkspace} onChange={(value) => patch('blockOutsideWorkspace', value)} /></section><section className="soft-card settings-block two-columns"><label>자식 프로세스<select value={draft.childProcess} onChange={(event) => patch('childProcess', event.target.value as CustomDraft['childProcess'])}><option value="allow-listed">허용 목록만 실행</option><option value="observe">관찰 후 허용</option><option value="block">모두 차단</option></select></label><label>민감 파일 접근<select value={draft.sensitiveFiles} onChange={(event) => patch('sensitiveFiles', event.target.value as CustomDraft['sensitiveFiles'])}><option value="block">차단</option><option value="warn">경고</option><option value="audit">기록만</option></select></label><label>지원 밖 Tool<select value={draft.unknownTool} onChange={(event) => patch('unknownTool', event.target.value as CustomDraft['unknownTool'])}><option value="approval">사용자 확인</option><option value="block">차단</option></select></label><label>복구 방식<select value={draft.recovery} onChange={(event) => patch('recovery', event.target.value as CustomDraft['recovery'])}><option value="manual">확인 후 복구</option><option value="automatic">자동 복구</option><option value="disabled">사용 안 함</option></select></label></section></div><aside className="soft-card policy-preview"><span className="page-eyebrow">POLICY SUMMARY</span><h4>이 설정의 예상 동작</h4><ul><li>{draft.blockOutsideWorkspace ? 'Workspace 외부 접근을 차단합니다.' : 'Workspace 외부 접근을 허용합니다.'}</li><li>민감 파일 접근은 <b>{draft.sensitiveFiles === 'block' ? '차단' : draft.sensitiveFiles === 'warn' ? '경고' : '감사 기록'}</b>합니다.</li><li>지원 범위 밖 Tool은 <b>{draft.unknownTool === 'approval' ? '사용자 확인' : '차단'}</b>합니다.</li><li>복구 방식은 <b>{draft.recovery === 'manual' ? '사용자 확인 후' : draft.recovery === 'automatic' ? '자동' : '사용 안 함'}</b>입니다.</li></ul><div className="diff-box"><b>템플릿 대비 변경</b><span>기준: {draft.base}</span><span>{dirty ? '초안에 저장 전 변경사항이 있습니다.' : '저장된 초안과 동일합니다.'}</span></div><div className="preview-actions"><button type="button" className="text-action" onClick={reset}>템플릿으로 초기화</button><button type="button" className="secondary-action" onClick={test}>정책 검증</button><button type="button" className="primary-action" onClick={save} disabled={!dirty}>초안 저장</button></div></aside></div></section>
}

function ToggleRow({ label, detail, checked, onChange }: { label: string; detail: string; checked: boolean; onChange: (value: boolean) => void }) {
  return <label className="toggle-row"><span><b>{label}</b><small>{detail}</small></span><input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} /><i aria-hidden="true" /></label>
}
