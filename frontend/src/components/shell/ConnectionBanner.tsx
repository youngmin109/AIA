import { Button } from '../common/Button'
import { isConnectionLost } from '../../api/connectionState'
import { useRunList } from '../../hooks/useRunList'

/** Shown only when the shared run-list poll gets no response twice in a row. */
export function ConnectionBanner() {
  const { connectionFailures = 0, refetch } = useRunList()
  if (!isConnectionLost(connectionFailures)) return null
  return (
    <div className="connection-banner" role="alert">
      <span>AIA 로컬 서버와 연결이 끊겼습니다. 자동으로 다시 연결을 시도합니다. 앱 창을 닫았다 다시 열어야 할 수도 있습니다.</span>
      <Button variant="text" onClick={refetch}>지금 다시 확인</Button>
    </div>
  )
}
