import { useState } from 'react'
import { Button } from '../common/Button'
import { GlossyIcon } from '../common/Glass'
import { ACCESS_LABEL, SCOPE_NOTE } from '../../api/permissionGrants'
import type { PermissionsRequest } from './codexConversation'

type Decision = 'turn' | 'session' | 'decline'

/** Codex asking to widen its sandbox. Nothing is preselected: the user decides, like in the Codex app. */
export function PermissionsCard({ request, disabled, onDecide }: {
  request: PermissionsRequest
  disabled: boolean
  onDecide: (decision: Decision) => boolean
}) {
  const [sent, setSent] = useState(false)
  const busy = disabled || sent

  function decide(decision: Decision) {
    if (onDecide(decision)) setSent(true)
  }

  return (
    <section className="glass-card question-card" aria-label="Codex 권한 요청">
      <div className="question-head">
        <GlossyIcon tone="danger" icon="lock" size="sm" />
        <strong>Codex가 권한을 더 달라고 해요</strong>
      </div>
      {request.reason && <p className="question-message">{request.reason}</p>}
      <ul className="permission-list">
        {request.network && (
          <li>
            <strong>인터넷 사용</strong>
            <span className="badge is-warn">AIA는 인터넷 통신을 감시하지 않아요</span>
          </li>
        )}
        {request.filesystem.map((entry, index) => (
          <li key={`${entry.access}:${entry.target}:${index}`}>
            <strong>{ACCESS_LABEL[entry.access]}</strong>
            <code>{entry.target}</code>
            <span className={`badge ${entry.scope === 'inside' ? 'is-neutral' : 'is-warn'}`}>{SCOPE_NOTE[entry.scope]}</span>
          </li>
        ))}
      </ul>
      <p className="faint-note">허용하면 Codex의 실행 권한이 늘어나요. AIA의 감시·복구 범위는 넓어지지 않으며, 결과에 보호 제한을 남기고 추가 복구 지점 저장은 중단해요.</p>
      <div className="dialog-actions">
        <Button variant="outline" disabled={busy} onClick={() => decide('decline')}>거절</Button>
        <Button variant="secondary" disabled={busy} onClick={() => decide('turn')}>이번 요청만 허용</Button>
        <Button variant="secondary" disabled={busy} onClick={() => decide('session')}>이번 실행 내내 허용</Button>
      </div>
    </section>
  )
}
