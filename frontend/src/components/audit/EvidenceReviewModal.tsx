import { Button } from '../common/Button'
import { Badge } from '../common/Badge'
import { GlossyIcon } from '../common/Glass'
import { useDialog } from '../common/useDialog'
import { displayStatus } from '../../api/display'
import { useShellStore } from '../../state/shellStore'
import { useEvidenceReview } from '../../hooks/useEvidenceReview'

/** Local "I looked at this" note for a flagged event. It never blocks, undoes, or re-judges anything. */
export function EvidenceReviewModal() {
  const { activeRunId } = useShellStore()
  const { pending, ack } = useEvidenceReview(activeRunId)
  if (!pending) return null
  return <ReviewDialog summary={pending.display_summary ?? pending.summary} decision={pending.display_decision ?? pending.decision} meta={[pending.tool_name, pending.target_label].filter(Boolean).join(' · ')} onAck={ack} />
}

function ReviewDialog({ summary, decision, meta, onAck }: { summary?: string; decision?: string; meta: string; onAck: (mark: 'problem' | 'reviewed') => void }) {
  // Escape leaves the note unanswered; only the explicit buttons record a mark.
  const ref = useDialog(true, () => {})
  return (
    <>
      <div className="glass-scrim" aria-hidden="true" />
      <div className="glass-dialog-layer">
        <div ref={ref} tabIndex={-1} className="glass-dialog review-dialog" role="dialog" aria-modal="true" aria-labelledby="review-title">
          <div className="approval-head">
            <GlossyIcon tone="danger" icon="alert" size="lg" />
            <div>
              <h2 id="review-title">확인이 필요한 사건이 있어요</h2>
              <p>{summary ?? '정책 사건이 기록됐어요.'}</p>
            </div>
          </div>
          <div className="badge-wrap">
            <Badge tone={decision === 'VIOLATION' ? 'bad' : 'warn'}>{decision ? displayStatus(decision) : '판정 불가'}</Badge>
            {meta && <Badge tone="neutral">{meta}</Badge>}
          </div>
          <p className="faint-note">이 표시는 이 PC의 화면에만 저장돼요. 실행을 막거나 되돌리지 않고, 사건의 판정도 바꾸지 않아요. 자세한 근거는 기록에서 계속 볼 수 있어요.</p>
          <div className="dialog-actions">
            <Button variant="secondary" className="is-danger" onClick={() => onAck('problem')}>문제로 표시</Button>
            <Button variant="cta" onClick={() => onAck('reviewed')}>확인했어요</Button>
          </div>
        </div>
      </div>
    </>
  )
}
