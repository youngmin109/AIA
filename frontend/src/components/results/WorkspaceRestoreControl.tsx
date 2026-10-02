import { useState } from 'react'
import type { RecoveryStatusView } from '../../api/resultTypes'
import { restoreWorkspace } from '../../api/endpoints'
import { useDialog } from '../common/useDialog'
import guardian from '../../assets/mascot/guardian-recovery.png'

const OPERATIONS: Record<string, string> = { REMOVE_CURRENT: '현재 항목 제거', RESTORE_CONTENT: '내용·유형 복원', RESTORE_MISSING: '삭제된 항목 복원' }
export function WorkspaceRestoreControl({ runId, recovery, onRestored }: { runId: string; recovery: RecoveryStatusView | null; onRestored: () => void }) {
  const [confirming, setConfirming] = useState(false)
  const [acknowledged, setAcknowledged] = useState(false)
  const [phase, setPhase] = useState<'idle' | 'working' | 'verified' | 'attention'>('idle')
  const [error, setError] = useState<string | null>(null)
  const ref = useDialog(confirming, () => { if (phase !== 'working') setConfirming(false) })
  if (!recovery) return <p className="validation-note">복구 가능 여부를 확인하는 중입니다.</p>
  const restoring = phase === 'working'
  async function restore() {
    if (!recovery?.preview_fingerprint || !acknowledged || restoring) return
    setPhase('working'); setError(null)
    try {
      const response = await restoreWorkspace(runId, recovery.preview_fingerprint)
      const restored = response.recovery_result as { recovery_status?: string } | undefined
      const integrity = response.integrity_result as { integrity_status?: string } | undefined
      setPhase(restored?.recovery_status === 'RESTORED' && integrity?.integrity_status === 'VERIFIED' ? 'verified' : 'attention')
      setConfirming(false)
      window.dispatchEvent(new CustomEvent('aia:result-updated', { detail: runId }))
      onRestored()
    } catch (failure) {
      setPhase('attention'); setError(failure instanceof Error ? failure.message : String(failure))
      onRestored()
    }
  }
  const success = phase === 'verified' || recovery.manual_recovery && recovery.record_verification === 'VALID' && recovery.recovery_status === 'RESTORED' && recovery.integrity_status === 'VERIFIED'
  return <div className="workspace-restore">
    {(restoring || success || phase === 'attention') && <div className={`recovery-journey is-${restoring ? 'working' : success ? 'verified' : 'attention'}`} role="status" aria-live="polite" aria-busy={restoring}>
      <div className="recovery-orbit" aria-hidden="true"><i /><i /><img src={guardian} alt="" /></div>
      <div><b>{restoring ? '복구와 무결성 검증을 처리하고 있어요' : success ? '복구·무결성 검증이 확인됐어요' : '복구 결과를 다시 확인해주세요'}</b><p>{restoring ? '실제 서버 응답을 기다리고 있습니다. 처리율이나 완료 상태를 임의로 표시하지 않습니다.' : success ? '복구 기록을 감사 결과와 함께 확인할 수 있습니다.' : '완료로 확정하지 않습니다. 복구 상태와 오류를 확인하세요.'}</p><div className="recovery-signal"><span>기준점 복원</span><span>SHA-256 검증</span><span>결과 기록</span></div></div>
    </div>}
    {recovery.record_verification && recovery.record_verification !== 'VALID' && <p role="alert" className="workspace-restore-error">이전 수동 복구 기록이 미검증 또는 손상 상태입니다. 원래 실행의 감사 검증과 별도로 확인해야 합니다.</p>}
    {error && <p role="alert" className="workspace-restore-error">복구 요청을 완료하지 못했습니다: {error}</p>}
    {recovery.workspace_matches && !recovery.manual_recovery && <p className="workspace-restore-note">작업공간이 기준점과 같습니다. 복구할 변경이 없습니다.</p>}
    {recovery.available && !recovery.workspace_matches && !success && <>
      <p>현재 작업공간 전체를 실행 전 기준점으로 복원합니다. 이 실행 이후 사용자나 다른 프로그램이 만든 변경도 영향을 받습니다.</p>
      {!confirming ? <button type="button" className="cta-button" onClick={() => { setAcknowledged(false); setConfirming(true) }}>복구 항목 확인</button> : <div ref={ref} className="workspace-restore-confirm" role="alertdialog" aria-modal="true" aria-label="전체 작업공간 복구 확인">
        <strong>전체 작업공간 복구 · 이후 변경도 되돌아갑니다</strong>
        <p>기준 시각: {recovery.checkpoint_created_at ? new Date(recovery.checkpoint_created_at).toLocaleString('ko-KR') : '확인 전'} · 영향 항목 {recovery.change_count ?? '확인 전'}개</p>
        <div className="restore-preview-list">{(recovery.change_preview ?? []).map(item => <div key={`${item.path}:${item.operation}`}><span>{item.path}</span><b>{OPERATIONS[item.operation] ?? '확인 필요'}</b></div>)}</div>
        {recovery.preview_truncated && <p>목록은 200개까지만 표시됩니다. 나머지 항목도 복구 대상입니다.</p>}
        <p className="validation-note">필요한 현재 변경은 먼저 별도로 보관하세요. 자동 백업은 제공하지 않습니다. 다른 편집기·프로그램의 쓰기 작업을 멈춰주세요.</p>
        <label className="restore-acknowledgement"><input type="checkbox" checked={acknowledged} disabled={restoring} onChange={event => setAcknowledged(event.target.checked)} />복구 범위와 이후 변경에 미치는 영향을 이해했습니다.</label>
        <div className="workspace-restore-actions"><button type="button" className="cta-button" disabled={!acknowledged || restoring || !recovery.preview_fingerprint} onClick={restore}>{restoring ? '복구·검증 처리 중…' : '전체 작업공간 복구'}</button><button type="button" className="secondary-button" disabled={restoring} onClick={() => setConfirming(false)}>취소</button></div>
      </div>}
    </>}
    {!recovery.available && !recovery.manual_recovery && !recovery.workspace_matches && <p className="validation-note">현재 복구할 수 없습니다. <span title={recovery.reason ?? undefined}>{recovery.reason === 'RUN_IS_ACTIVE' ? '먼저 실행을 종료해주세요.' : '유효한 복구 기준점과 실행 결과를 확인해주세요.'}</span></p>}
  </div>
}
