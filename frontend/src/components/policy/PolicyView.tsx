import { useEffect, useState } from 'react'
import { listProfiles, type PolicyProfile } from '../../api/endpoints'
import { readDefaultPolicyProfile, writeDefaultPolicyProfile } from './policyStorage'

const isStandardProfile = (profile: PolicyProfile) => profile.value !== 'CUSTOM'

export function PolicyView() {
  const [profiles, setProfiles] = useState<PolicyProfile[]>([])
  const [selected, setSelected] = useState<string | null>(null)

  useEffect(() => {
    listProfiles()
      .then((list) => {
        const standard = list.filter(isStandardProfile)
        setProfiles(standard)
        const saved = readDefaultPolicyProfile()
        setSelected(saved && standard.some((profile) => profile.value === saved) ? saved : standard[0]?.value ?? null)
      })
      .catch(() => setProfiles([]))
  }, [])

  function choose(value: string) {
    setSelected(value)
    writeDefaultPolicyProfile(value)
  }

  return (
    <div className="dashboard-view">
      <p className="policy-page-heading">다음 보호 실행에 적용할 기본 정책을 선택합니다.</p>
      <div className="policy-view-notice">
        선택은 <strong>이 브라우저의 다음 보호 실행 기본값</strong>으로 저장됩니다. 보호 세팅 창에서 실행마다 다시 선택할 수 있으며, 이미 실행 중인 세션의 정책은 바뀌지 않습니다. 직접 설정 정책은 실행 시 <code className="mono">--policy &lt;json&gt;</code>으로 지정합니다.
      </div>
      <div className="policy-grid">
        {profiles.map((profile) => {
          const isActive = selected === profile.value
          return (
            <article key={profile.value} className={`card policy-choice${isActive ? ' is-active' : ''}`}>
              <span className={`badge${isActive ? ' is-accent' : ''}`}>{isActive ? '다음 실행 기본값' : '선택 가능'}</span>
              <h3>{profile.display_name}</h3>
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
