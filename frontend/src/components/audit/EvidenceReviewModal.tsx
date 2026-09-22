import { useShellStore } from '../../state/shellStore'
import { useEvidenceReview } from '../../hooks/useEvidenceReview'

export function EvidenceReviewModal() {
  const { activeRunId } = useShellStore()
  const { pending, ack } = useEvidenceReview(activeRunId)

  if (!pending) return null

  const decision = pending.display_decision ?? pending.decision
  const meta = [pending.tool_name, pending.target_label].filter(Boolean).join(' · ')

  return (
    <div className="modal-overlay" role="dialog" aria-modal="true" aria-label="증거 확인">
      <div className="modal-panel" style={{ maxWidth: 480 }}>
        <div className="modal-header">
          <h2>확인이 필요한 사건이 있습니다</h2>
        </div>
        <div className="modal-body">
          <span className={`badge is-${decision === 'VIOLATION' ? 'bad' : 'warn'}`}>{decision ?? '판정 불가'}</span>
          <p style={{ color: 'var(--text)', fontWeight: 600, marginTop: 10 }}>{pending.display_summary ?? pending.summary}</p>
          {meta && <p style={{ fontSize: 12, marginTop: 4 }}>{meta}</p>}
          <div className="policy-view-notice" style={{ marginTop: 14, marginBottom: 0 }}>
            이 표시는 이 브라우저에만 저장됩니다. 실행을 막거나 되돌리지 않으며, 사건 자체의 판정도 바뀌지 않습니다. 자세한 근거는 실시간 기록 또는 감사 기록에서 계속 확인할 수 있습니다.
          </div>
          <div style={{ display: 'flex', gap: 8, marginTop: 16, justifyContent: 'flex-end' }}>
            <button type="button" className="icon-button-text" onClick={() => ack('problem')}>
              문제로 표시
            </button>
            <button type="button" className="cta-button" style={{ width: 'auto', padding: '8px 16px' }} onClick={() => ack('reviewed')}>
              검토 완료로 표시
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
