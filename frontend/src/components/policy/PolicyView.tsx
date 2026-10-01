import { useEffect, useState } from 'react'
import { listProfiles, type PolicyProfile } from '../../api/endpoints'
import { readDefaultPolicyProfile, writeDefaultPolicyProfile } from './policyStorage'

// Four operational choices make the policy intent clear without changing the
// immutable Core profiles. The wording follows Microsoft's agent-security
// principles: least privilege, human oversight for high-impact actions,
// auditable operation, and a deliberately limited observation-only mode.
const PROFILE_GUIDANCE: Record<string, { title: string; summary: string; controls: string[]; tone: string }> = {
  PROTECTED_DEVELOPMENT: {
    title: '표준 보호',
    summary: '일반적인 로컬 개발에 권장합니다. Workspace 범위를 우선하고 민감정보·대표적인 파괴 명령을 통제합니다.',
    controls: ['Workspace 최소 권한', '민감정보 보호', '감사 기록'],
    tone: 'standard',
  },
  BASIC_DEVELOPMENT: {
    title: '협업 개발',
    summary: '일반 코드 작업 흐름을 유지하면서 .env 삭제와 위험한 데이터베이스·Git 명령을 통제합니다.',
    controls: ['일반 작업 허용', '위험 명령 통제', '감사 기록'],
    tone: 'collaboration',
  },
  CONSERVATIVE_SECURITY: {
    title: '중요 자산 보호',
    summary: '비밀정보와 핵심 변경이 있는 작업에 사용합니다. 고위험 작업은 더 엄격히 차단·기록합니다.',
    controls: ['강화된 최소 권한', '고위험 작업 통제', '복구·무결성 확인'],
    tone: 'strict',
  },
  FREE_DEVELOPMENT: {
    title: '관찰 전용',
    summary: '정책을 시험하거나 개발 흐름을 점검할 때 사용합니다. 위험 행위를 주로 기록하므로 실사용 보호에는 권장하지 않습니다.',
    controls: ['행동 관찰', '감사 기록', '실사용 비권장'],
    tone: 'observe',
  },
}

export function PolicyView() {
  const [profiles, setProfiles] = useState<PolicyProfile[]>([])
  const [selected, setSelected] = useState<string | null>(null)

  useEffect(() => {
    listProfiles()
      .then((list) => {
        setProfiles(list)
        const standardProfiles = list.filter((profile) => profile.value !== 'CUSTOM')
        const saved = readDefaultPolicyProfile()
        setSelected(saved && standardProfiles.some((profile) => profile.value === saved) ? saved : standardProfiles[0]?.value ?? null)
      })
      .catch(() => setProfiles([]))
  }, [])

  function choose(value: string) {
    setSelected(value)
    writeDefaultPolicyProfile(value)
  }

  return (
    <div className="dashboard-view">
      <div className="policy-page-heading"><span>MICROSOFT AGENT SECURITY PRINCIPLES</span><h2>보호 정책</h2><p>최소 권한, 고위험 작업의 사용자 관여, 감사 가능성을 기준으로 다음 보호 실행에 적용합니다.</p></div>
      <div className="policy-view-notice">
        선택한 정책은 <strong>다음에 시작하는 새 보호 실행</strong>에 고정됩니다. 이미 실행 중인 세션의 정책은 바뀌지 않습니다. 직접 설정 정책은 CLI에서 Strict Validation을 통과한 JSON으로만 등록할 수 있습니다.
      </div>
      <div className="policy-grid">
        {profiles.filter((profile) => profile.value !== 'CUSTOM').map((profile) => {
          const isActive = selected === profile.value
          const guidance = PROFILE_GUIDANCE[profile.value] ?? { title: profile.label, summary: profile.description ?? '설명이 제공되지 않았습니다.', controls: [], tone: 'standard' }
          return (
            <article key={profile.value} className={`card policy-choice policy-choice-${guidance.tone}${isActive ? ' is-active' : ''}`}>
            <span className={`badge${isActive ? ' is-accent' : ''}`}>{isActive ? '다음 실행 기본값' : '선택 가능'}</span>
              <h3>{guidance.title}</h3>
              <p>{guidance.summary}</p>
              <ul className="policy-control-list">{guidance.controls.map((control) => <li key={control}>{control}</li>)}</ul>
              <button type="button" className="icon-button-text" disabled={isActive} onClick={() => choose(profile.value)}>
                {isActive ? '선택됨' : '기본값으로 선택'}
              </button>
            </article>
          )
        })}
        {profiles.length === 0 && <p className="empty-hint">보호 정책 목록을 불러오지 못했습니다.</p>}
      </div>
    </div>
  )
}
