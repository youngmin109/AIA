import { useState } from 'react'
import { createPortal } from 'react-dom'
import { Button } from '../common/Button'
import { Icon } from '../common/Icon'
import { RoundAction } from '../common/Glass'
import { GuardianFigure } from '../common/GuardianAvatar'
import { useDialog } from '../common/useDialog'
import type { RecoveryStatusView } from '../../api/resultTypes'
import { restoreWorkspace } from '../../api/endpoints'
import { restoreSteps, type IntegrityRecord, type RestoreRecord } from '../../api/resultSummary'

const OPERATIONS: Record<string, string> = { REMOVE_CURRENT: '현재 항목 제거', RESTORE_CONTENT: '내용·유형 복원', RESTORE_MISSING: '삭제된 항목 복원' }

export interface RestoreOutcome {
  recovery: RestoreRecord | null
  integrity: IntegrityRecord | null
  error: string | null
  checkpointAt: string | null
}

function timeLabel(value?: string | null): string | null {
  if (!value) return null
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? null : date.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', hour12: false })
}

/** ⑦ step 1: confirm the whole-workspace restore. The server refuses without confirm + fingerprint. */
export function RestoreDialog({ runId, recovery, onClose, onDone }: {
  runId: string
  recovery: RecoveryStatusView
  onClose: () => void
  onDone: (outcome: RestoreOutcome) => void
}) {
  const [acknowledged, setAcknowledged] = useState(false)
  const [restoring, setRestoring] = useState(false)
  const ref = useDialog(true, () => { if (!restoring) onClose() })

  async function restore() {
    if (!recovery.preview_fingerprint || !acknowledged || restoring) return
    setRestoring(true)
    try {
      const response = await restoreWorkspace(runId, recovery.preview_fingerprint, recovery.checkpoint_id)
      onDone({
        recovery: (response.recovery_result as RestoreRecord | undefined) ?? null,
        integrity: (response.integrity_result as IntegrityRecord | undefined) ?? null,
        error: null,
        checkpointAt: recovery.checkpoint_created_at ?? null,
      })
    } catch (failure) {
      onDone({ recovery: null, integrity: null, error: failure instanceof Error ? failure.message : String(failure), checkpointAt: recovery.checkpoint_created_at ?? null })
    } finally {
      window.dispatchEvent(new CustomEvent('aia:result-updated', { detail: runId }))
    }
  }

  // Portaled to <body>: an animated ancestor would otherwise clip the fixed scrim.
  return createPortal(
    <>
      <div className="glass-scrim" aria-hidden="true" onClick={() => { if (!restoring) onClose() }} />
      <div className="glass-dialog-layer">
        <div ref={ref} tabIndex={-1} className="glass-dialog restore-dialog" role="alertdialog" aria-modal="true" aria-labelledby="restore-title" aria-busy={restoring}>
          <h2 id="restore-title" className="dialog-title">작업 폴더를 {recovery.checkpoint_id ? '선택한 지점' : '실행 전'}으로 되돌릴까요?</h2>
          <p className="muted dialog-text">
            기준점 {timeLabel(recovery.checkpoint_created_at) ?? '확인 전'} · 바뀔 항목 {recovery.change_count ?? '확인 전'}개.
            이 실행 이후 다른 프로그램이나 사용자가 만든 변경도 함께 되돌아가요.
          </p>
          <ul className="restore-preview">
            {(recovery.change_preview ?? []).map(item => (
              <li key={`${item.path}:${item.operation}`}><span className="mono">{item.path}</span><span className="badge is-neutral">{OPERATIONS[item.operation] ?? '확인 필요'}</span></li>
            ))}
          </ul>
          {recovery.preview_truncated && <p className="faint-note">목록은 200개까지만 보여요. 나머지 항목도 되돌려요.</p>}
          <div className="glass-notice is-warning"><div><strong>필요한 현재 변경은 먼저 따로 보관하세요</strong><p>자동 백업은 없어요. 다른 편집기·프로그램의 저장도 잠시 멈춰 주세요.</p></div></div>
          <label className="restore-ack">
            <input type="checkbox" checked={acknowledged} disabled={restoring} onChange={event => setAcknowledged(event.target.checked)} />
            되돌리는 범위와 이후 변경에 미치는 영향을 이해했어요.
          </label>
          <div className="dialog-actions">
            <Button variant="secondary" disabled={restoring} onClick={onClose}>취소</Button>
            <Button variant="cta" disabled={!acknowledged || restoring || !recovery.preview_fingerprint} onClick={restore}>
              {restoring ? <><span className="spinner" aria-hidden="true" />되돌리고 검증하는 중…</> : '작업 폴더 되돌리기'}
            </Button>
          </div>
        </div>
      </div>
    </>,
    document.body,
  )
}

/** ⑦ step 2: what the restore and the integrity check reported. Never upgrades a partial result to success. */
export function RestoreComplete({ outcome, onBack, onHome }: { outcome: RestoreOutcome; onBack: () => void; onHome: () => void }) {
  const restored = outcome.recovery?.recovery_status === 'RESTORED'
  const verified = outcome.integrity?.integrity_status === 'VERIFIED'
  const success = !outcome.error && restored && verified
  const checkpoint = timeLabel(outcome.checkpointAt)
  const steps = restoreSteps(outcome.recovery, outcome.integrity, checkpoint)
  return (
    <div className="restore-complete view-enter" role="status" aria-live="polite">
      <div className={`restore-ring${success ? '' : ' is-attention'}`}>
        <GuardianFigure state={success ? 'recovery' : 'review'} alt={success ? '복구를 마친 아이아 가디언' : '복구 결과 확인을 요청하는 아이아 가디언'} />
        <span className="restore-ring-mark" aria-hidden="true"><Icon name={success ? 'check' : 'alert'} size={22} /></span>
      </div>
      <h1>{success ? '작업 폴더를 되돌렸어요' : '되돌리기 결과를 확인해 주세요'}</h1>
      <p className="muted">
        {outcome.error
          ? `요청을 끝내지 못했어요: ${outcome.error}`
          : success
            ? `선택한 복구 기준점${checkpoint ? `(${checkpoint})` : ''}과 같아요 · SHA-256 일치`
            : '복구와 무결성 검증 결과가 완전히 확인되지 않았어요. 완료로 보지 마세요.'}
      </p>
      {!outcome.error && (
        <ol className="glass is-soft restore-steps">
          {steps.map(step => (
            <li key={step.key} className={`is-${step.state}`}>
              <span className="restore-step-mark" aria-hidden="true"><Icon name={step.state === 'done' ? 'check' : 'alert'} size={16} /></span>
              <span><strong>{step.label}</strong><small>{step.detail}</small></span>
            </li>
          ))}
        </ol>
      )}
      {(outcome.recovery?.failed_paths?.length ?? 0) > 0 && (
        <details className="glass-card restore-failed"><summary>되돌리지 못한 경로 {outcome.recovery?.failed_paths?.length}개</summary>
          <ul>{outcome.recovery?.failed_paths?.map(path => <li key={path} className="mono">{path}</li>)}</ul>
        </details>
      )}
      <div className="restore-actions">
        <Button variant="secondary" onClick={onBack}>결과로 돌아가기</Button>
        <RoundAction small onClick={onHome}>홈으로</RoundAction>
      </div>
      <p className="faint-note">되돌린 기록은 감사 기록에 따로 남아요. 원래 실행의 결과와는 별개예요.</p>
    </div>
  )
}
