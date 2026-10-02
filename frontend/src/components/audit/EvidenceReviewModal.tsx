import { Button } from '../common/Button'
import { Badge } from '../common/Badge'
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
      <div className="modal-panel review-dialog">
        <div className="modal-header">
          <h2>확인이 필요한 사건이 있습니다</h2>
        </div>
        <div className="modal-body">
          <Badge tone={decision === 'VIOLATION' ? 'bad' : 'warn'}>{decision ?? '판정 불가'}</Badge>
          <p className="review-summary">{pending.display_summary ?? pending.summary}</p>
          {meta && <p className="review-meta">{meta}</p>}
          <div className="policy-view-notice review-notice">
            이 표시는 이 브라우저에만 저장됩니다. 실행을 막거나 되돌리지 않으며, 사건 자체의 판정도 바뀌지 않습니다. 자세한 근거는 실시간 기록 또는 감사 기록에서 계속 확인할 수 있습니다.
          </div>
          <div className="dialog-actions">
            <Button variant="iconText" onClick={() => ack('problem')}>
              문제로 표시
            </Button>
            <Button variant="cta" className="is-compact" onClick={() => ack('reviewed')}>
              검토 완료로 표시
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}
