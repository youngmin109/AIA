import { useState } from 'react'
import { Button } from '../common/Button'
import { TileCorner, type GlossTone } from '../common/Glass'
import { Icon, type IconName } from '../common/Icon'
import { PolicyPreview } from './PolicyPreview'
import type { PolicyProfile } from '../../api/endpoints'
import { useProfiles } from '../../hooks/useProfiles'
import { readDefaultPolicyProfile, writeDefaultPolicyProfile } from './policyStorage'
import { CustomPolicyEditor } from './CustomPolicyEditor'

type SupportStatus = '지원' | '부분 지원'

const CARD_LOOK: Array<{ tone: GlossTone; icon: IconName }> = [
  { tone: 'hook', icon: 'shieldPlain' },
  { tone: 'file', icon: 'chat' },
  { tone: 'process', icon: 'lock' },
  { tone: 'amber', icon: 'search' },
]

// Only behaviour the engine performs today is listed here. Planned work stays
// in the docs so the console never implies protection that does not exist.
const ENGINE_FACTS: Array<{ title: string; items: Array<{ title: string; description: string; status: SupportStatus }> }> = [
  { title: '실행 범위', items: [
    { title: '작업공간 범위', description: '보호 실행 시작 시 지정한 작업공간을 관찰과 복구의 기준으로 사용합니다.', status: '지원' },
    { title: '작업공간 밖 쓰기', description: '권한이 "승인 요청"·"나 대신 승인"이면 Codex 샌드박스가 제한합니다. "전체 권한"에서는 제한하지 않고, AIA는 명령을 실행 전에 검사만 합니다. 작업 폴더 밖 변경은 되돌릴 수 없습니다.', status: '부분 지원' },
    { title: '도구·명령 범위', description: '에이전트가 요청하는 도구와 위험 명령을 실행 전에 평가합니다.', status: '부분 지원' },
    { title: '사용자 확인', description: '지원 범위 밖 도구는 사용자에게 확인합니다. 정책상 금지된 동작은 허용할 수 없습니다.', status: '부분 지원' },
  ] },
  { title: '런타임 보호', items: [
    { title: '정책 고정과 작업공간 중복 실행 방지', description: '실행 중 정책 변경과 같은 작업공간의 중복 보호 실행을 막습니다.', status: '지원' },
    { title: '복구 기준점', description: '실행 전 파일 존재 여부와 SHA-256 파일 목록을 복구 기준점으로 만듭니다.', status: '지원' },
    { title: '프로세스 트리 관찰', description: '등록된 에이전트 시작 프로세스와 자식 프로세스를 관찰하고, 사용자가 중지하면 그 트리만 종료합니다. 정책 위반에 따른 실제 Codex 자동 종료는 아직 검증하지 않았습니다.', status: '부분 지원' },
  ] },
  { title: '데이터 보호', items: [
    { title: '비밀정보 경로 보호', description: '프로필별 .env 등 민감 경로 규칙을 평가합니다.', status: '지원' },
    { title: '증거 표시 제한', description: '감사 요약은 원문을 제한합니다. 작업·승인 화면에는 요청된 명령이 표시될 수 있지만 대화 기록은 저장하지 않습니다. 진단 묶음은 민감정보를 제외합니다.', status: '지원' },
  ] },
  { title: '탐지 및 대응', items: [
    { title: '증거 정규화·관련성 확인', description: '실행 요청·프로세스·파일 증거를 하나의 행위로 연결합니다.', status: '지원' },
    { title: '실행 유지 · 통제 승인 · 대응 거부', description: '정책·귀속·센서 상태에 따라 집행 관문이 대응을 정합니다.', status: '지원' },
    { title: '복구·무결성 검증', description: '복구 기준점 복원 후 경로·SHA-256 결과를 확인합니다.', status: '지원' },
  ] },
  { title: '감사 기록', items: [
    { title: '감사 기록과 결과 묶음', description: '세션별 증거·판정·조치·무결성 결과를 묶어 확정합니다.', status: '지원' },
    { title: '결과 묶음 무결성 검증', description: '저장된 결과 묶음의 해시와 파일 목록을 검증해 변경·손상 여부를 확인합니다.', status: '지원' },
  ] },
]

/** ⑧ Policy: pick the next run's default template and dry-run a command against every template. */
export function PolicyView() {
  const { profiles: all, error } = useProfiles()
  const profiles = all
  const [chosen, setChosen] = useState<string | null>(readDefaultPolicyProfile)
  const [notice, setNotice] = useState('')
  const selected = profiles.some(profile => profile.value === chosen) ? chosen : profiles[0]?.value ?? null

  function choose(profile: PolicyProfile) {
    setChosen(profile.value)
    writeDefaultPolicyProfile(profile.value)
    setNotice(`${profile.display_name}을(를) 다음 보호 실행의 기본값으로 정했어요.`)
  }

  return (
    <div className="page-stack policy-page view-enter">
      <header className="page-head">
        <div>
          <h1>정책</h1>
          <p>다음 보호 실행에 쓸 규칙을 골라요. 실행 중에는 바뀌지 않아요.</p>
        </div>
      </header>
      {error && <div className="glass-notice is-warning" role="alert"><strong>정책을 불러오지 못했어요</strong><p>잠시 뒤 다시 열어 주세요.</p></div>}
      {notice && <div className="glass-notice is-success" role="status"><strong>{notice}</strong><p>새 보호 실행 시트에서 실행마다 다시 고를 수 있어요.</p></div>}

      <section className="policy-cards" aria-label="정책 템플릿">
        {profiles.map((profile, index) => {
          const on = profile.value === selected
          const look = CARD_LOOK[index % CARD_LOOK.length]
          return (
            <button key={profile.value} type="button" className={`glass-card policy-card${on ? ' is-selected' : ''}`} aria-pressed={on} onClick={() => choose(profile)}>
              <TileCorner tone={look.tone} icon={look.icon} />
              <span className={`badge ${on ? 'is-ok' : 'is-neutral'}`}>{on ? <><Icon name="check" size={14} />사용 중</> : '선택하기'}</span>
              <strong>{profile.display_name}</strong>
              <span className="policy-card-text">{profile.description ?? '설명이 제공되지 않았어요.'}</span>
              {profile.english_name && <span className="policy-card-tag">{profile.english_name}</span>}
            </button>
          )
        })}
        {profiles.length === 0 && !error && <p className="faint-note">정책을 불러오는 중이에요…</p>}
      </section>

      {selected === 'CUSTOM' ? <CustomPolicyEditor onSaved={() => setNotice('사용자 지정 규칙을 저장했어요. 다음 보호 실행에 적용할 수 있어요.')} /> : <>
        <PolicyPreview key={selected} profile={selected} profiles={profiles.filter(profile => profile.value !== 'CUSTOM')} />
      </>}

      <section className="glass-card policy-facts" aria-label="AIA가 실제로 하는 일">
        <h2>AIA가 실제로 하는 일</h2>
        {ENGINE_FACTS.map(group => (
          <details key={group.title}>
            <summary>{group.title} <span className="muted">{group.items.length}개</span></summary>
            <ul>
              {group.items.map(item => (
                <li key={item.title}>
                  <div><strong>{item.title}</strong><p>{item.description}</p></div>
                  <span className={`status-pill ${item.status === '지원' ? 'good' : 'warning'}`}>{item.status}</span>
                </li>
              ))}
            </ul>
          </details>
        ))}
        <p className="faint-note">이 목록에는 엔진이 지금 실제로 하는 일만 적었어요. 사용자 지정에서는 세부 규칙을 검증하고 저장한 뒤 새 보호 실행에 적용할 수 있어요.</p>
        <Button variant="text" onClick={() => document.getElementById('policy-preview-target')?.focus()}>명령 판정해 보기 <Icon name="arrowRight" size={14} /></Button>
      </section>
    </div>
  )
}
