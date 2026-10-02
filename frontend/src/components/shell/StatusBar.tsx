import { displayStatus } from '../../api/display'
import { usePreflight } from '../../hooks/usePreflight'
import { useRunList, isRunActive } from '../../hooks/useRunList'

export function StatusBar() {
  const { data: preflight, error } = usePreflight()
  const { data: runs } = useRunList()
  const hookTrustStatus = preflight?.hook_trust?.status ?? 'UNKNOWN'
  const hookOk = ['TRUSTED', 'MANAGED'].includes(hookTrustStatus)
  const activeRuns = (runs ?? []).filter(isRunActive).length

  return (
    <div className="status-bar">
      <span className="status-bar-item">
        <span className={`status-dot ${hookOk ? 'is-ok' : 'is-warn'}`} />
        보호 연결: {error ? '재확인 필요' : hookOk ? '신뢰 승인됨' : hookTrustStatus === 'MANUAL_REVIEW_REQUIRED' ? 'Codex 신뢰 승인 필요' : displayStatus(hookTrustStatus)}
      </span>
      <span className="status-bar-item">
        <span className={`status-dot ${error ? 'is-bad' : preflight ? 'is-ok' : 'is-warn'}`} />
        {error ? '로컬 서버 연결 확인 필요' : preflight ? '로컬 서버 연결됨' : '로컬 서버 확인 중'}
      </span>
      <span className="status-bar-item">활성 세션 {activeRuns}건</span>
      <div className="status-bar-spacer" />
      <span>AIA · 로컬 전용 콘솔</span>
    </div>
  )
}
