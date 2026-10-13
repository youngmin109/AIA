import { Button } from '../common/Button'
import { GlossyIcon, StatusDot } from '../common/Glass'
import { Icon } from '../common/Icon'
import { connectorsOnFirst, connectorSummary, connectorTone } from '../../api/connectorView'
import { useCodexConnectors } from '../../hooks/useCodexConnectors'

/** /mcp: the conversation's connectors, view only. Installing and signing in stay in the Codex app. */
export function ConnectorsCard({ runId, onClose }: { runId: string; onClose: () => void }) {
  const { connectors, error, reload } = useCodexConnectors(runId, true)
  return (
    <section className="glass-card question-card" aria-label="커넥터">
      <div className="question-head">
        <GlossyIcon tone="amber" icon="tree" size="sm" />
        <strong>커넥터</strong>
        <span className="badge is-warn">AIA 보호 범위 밖</span>
        <Button variant="text" className="is-compact" onClick={reload}>다시 확인</Button>
        <Button variant="icon" className="aia-note-close" onClick={onClose} aria-label="닫기"><Icon name="close" size={14} /></Button>
      </div>
      {error && <p className="danger-text">커넥터 목록을 불러오지 못했어요. {error}</p>}
      {!error && connectors === null && <p className="muted">불러오는 중…</p>}
      {connectors?.length === 0 && <p className="muted">이 대화에 연결된 외부 도구가 없어요.</p>}
      {connectors && connectors.length > 0 && (
        <ul className="permission-list">
          {connectorsOnFirst(connectors).map(connector => (
            <li key={connector.name}>
              <StatusDot tone={connectorTone(connector)} />
              <strong>{connector.name}</strong>
              <span className="muted">{connectorSummary(connector)}</span>
              {connector.error && <span className="badge is-warn">{connector.error}</span>}
            </li>
          ))}
        </ul>
      )}
      <p className="faint-note">이 도구들은 AIA 실행 전 검사를 거치지 않을 수 있어서 차단·기록되지 않을 수 있어요. 보호 실행에서 켜고 끄기는 설정 › 외부 도구에서, 설치·로그인은 Codex 앱에서 하세요.</p>
    </section>
  )
}
