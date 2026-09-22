import { useShellStore } from '../../state/shellStore'
import { usePreflight } from '../../hooks/usePreflight'

export function StatusBar() {
  const { openTabs } = useShellStore()
  const { data: preflight, error } = usePreflight()
  const hookTrustStatus = preflight?.hook_trust?.status ?? 'UNKNOWN'
  const hookOk = ['TRUSTED', 'MANAGED'].includes(hookTrustStatus)

  return (
    <div className="status-bar">
      <span className="status-bar-item">
        <span className={`status-dot ${hookOk ? 'is-ok' : 'is-warn'}`} />
        Hook Trust: {hookOk ? '신뢰됨' : hookTrustStatus}
      </span>
      <span className="status-bar-item">
        <span className={`status-dot ${error ? 'is-bad' : 'is-ok'}`} />
        {error ? '로컬 서버 연결 확인 필요' : '로컬 서버 연결됨'}
      </span>
      <span className="status-bar-item">활성 세션 {openTabs.length}건</span>
      <div className="status-bar-spacer" />
      <span>AIA · 로컬 전용 콘솔</span>
    </div>
  )
}
