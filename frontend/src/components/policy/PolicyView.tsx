import { useEffect, useState } from 'react'
import { listProfiles, type PolicyProfile } from '../../api/endpoints'
import { readDefaultPolicyProfile, writeDefaultPolicyProfile } from './policyStorage'

export function PolicyView() {
  const [profiles, setProfiles] = useState<PolicyProfile[]>([])
  const [selected, setSelected] = useState<string | null>(null)

  useEffect(() => {
    listProfiles()
      .then((list) => {
        setProfiles(list)
        setSelected(readDefaultPolicyProfile() ?? list[0]?.value ?? null)
      })
      .catch(() => setProfiles([]))
  }, [])

  function choose(value: string) {
    setSelected(value)
    writeDefaultPolicyProfile(value)
  }

  return (
    <div className="dashboard-view">
      <div className="policy-page-heading"><span>POLICY CONFIGURATION</span><h2>정책 설정</h2><p>선택한 정책은 다음 보호 실행에 고정되며, 실행 중에는 변경되지 않습니다.</p></div>
      <div className="policy-view-notice">
        선택한 프로필은 <strong>다음에 시작하는 새 보호 실행</strong>의 기본값으로만 저장됩니다(이 브라우저에만 저장됨). 이미 실행 중인 세션의 정책은 바뀌지 않습니다.
      </div>
      <div className="policy-grid">
        {profiles.map((profile) => {
          const isActive = selected === profile.value
          return (
            <article key={profile.value} className={`card policy-choice${isActive ? ' is-active' : ''}`}>
              <span className={`badge${isActive ? ' is-accent' : ''}`}>{isActive ? '다음 실행 기본값' : '선택 가능'}</span>
              <h3>{profile.label}</h3>
              <p>{profile.description ?? '설명이 제공되지 않았습니다.'}</p>
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
