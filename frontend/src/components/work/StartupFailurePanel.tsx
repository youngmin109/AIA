import { Button } from '../common/Button'
import { Icon } from '../common/Icon'
import { GlossyIcon } from '../common/Glass'
import { startupFailureView } from '../../api/startupFailure'

/** A failed run explained in plain words: never shown as a finished task. */
export function StartupFailurePanel({ error, workspace, onRestart, onOpenResult }: {
  error?: string | null
  workspace?: string | null
  onRestart: () => void
  onOpenResult?: () => void
}) {
  const failure = startupFailureView(error, workspace)
  return (
    <div className="glass is-soft work-empty work-ended work-failed view-enter" role="alert">
      <GlossyIcon tone="amber" icon="alertCircle" size="lg" />
      <strong>{failure.title}</strong>
      <span className="muted">{failure.reason}</span>
      {failure.item && <code className="work-failed-item">{failure.item}</code>}
      {failure.hint && <span className="muted">{failure.hint}</span>}
      <Button variant="cta" onClick={onRestart}><Icon name="plus" size={16} />다시 시작하기</Button>
      {onOpenResult && (
        <Button variant="text" onClick={onOpenResult}>기록에서 결과 보기 <Icon name="arrowRight" size={14} /></Button>
      )}
      {failure.detail && (
        <details className="work-failed-detail">
          <summary>오류 원문</summary>
          <code>{failure.detail}</code>
        </details>
      )}
    </div>
  )
}
