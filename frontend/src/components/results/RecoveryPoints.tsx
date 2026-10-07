import { useCallback, useEffect, useState } from 'react'
import { apiGet, apiPost } from '../../api/client'
import { Button } from '../common/Button'
import { RestoreComplete, RestoreDialog, type RestoreOutcome } from './WorkspaceRestoreControl'
import type { RecoveryStatusView } from '../../api/resultTypes'
import { useShellStore } from '../../state/shellStore'

interface Point { checkpoint_id: string; created_at: string; kind: string; name: string; reason: string; validity: string; entry_count: number; can_restore: boolean }
interface PointList { points: Point[]; history: Array<{ saved_at?: string; checkpoint_id?: string; recovery_status?: string; integrity_status?: string; verification: string }>; run_ended: boolean; last_save_error?: string; limitation: string }
const KIND: Record<string, string> = { BASELINE: '실행 전', AUTO: '자동', MANUAL: '수동' }

export function RecoveryPoints({ runId }: { runId: string }) {
  const { activeView } = useShellStore()
  const [data, setData] = useState<PointList | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [name, setName] = useState('중요 작업 전')
  const [preview, setPreview] = useState<RecoveryStatusView | null>(null)
  const [outcome, setOutcome] = useState<RestoreOutcome | null>(null)
  const load = useCallback(() => apiGet<PointList>(`/api/runs/${encodeURIComponent(runId)}/checkpoints`)
    .then(result => { setData(result); setError('') }).catch(failure => { setData(null); setError(String(failure)) }), [runId])
  useEffect(() => {
    if (activeView !== 'history') return
    let cancelled = false
    let timer: ReturnType<typeof setTimeout>
    const refresh = async () => {
      await load()
      if (!cancelled) timer = window.setTimeout(refresh, 10_000)
    }
    refresh()
    window.addEventListener('aia:result-updated', load)
    return () => { cancelled = true; clearTimeout(timer); window.removeEventListener('aia:result-updated', load) }
  }, [load, activeView])
  async function save() {
    setBusy(true); setError('')
    try { await apiPost(`/api/runs/${encodeURIComponent(runId)}/checkpoints`, { name }); await load() }
    catch (failure) { setError(String(failure)) }
    finally { setBusy(false) }
  }
  async function inspect(point: Point) {
    setBusy(true); setError('')
    try {
      const status = await apiGet<RecoveryStatusView>(`/api/runs/${encodeURIComponent(runId)}/recovery?checkpoint_id=${encodeURIComponent(point.checkpoint_id)}`)
      if (!status.available) throw new Error('실행 종료와 유효한 복구 지점을 먼저 확인해 주세요.')
      setPreview({ ...status, checkpoint_id: point.checkpoint_id })
    } catch (failure) { setError(String(failure)) }
    finally { setBusy(false) }
  }
  return <section className="glass policy-facts recovery-points" aria-label="복구 지점과 복구 이력">
    <h2>복구 지점</h2>
    <p>실행 전 기준점은 계속 보존돼요. 작업 완료 후 조건을 충족하면 자동 저장하고, 직접 저장할 수도 있어요.</p>
    {data && !data.run_ended && <div className="policy-preview-form">
      <input className="glass-input" value={name} maxLength={80} onChange={event => setName(event.target.value)} aria-label="복구 지점 이름" />
      <Button variant="secondary" disabled={busy || !name.trim()} onClick={save}>{busy ? '저장 중…' : '현재 복구 지점 저장'}</Button>
    </div>}
    {!data && !error && <p>저장된 지점을 확인하는 중…</p>}
    {data?.points.map(point => <div className="glass-row point-row" key={point.checkpoint_id}>
      <div><strong>{point.name}</strong><p>{new Date(point.created_at).toLocaleString('ko-KR')} · {KIND[point.kind] ?? '확인 필요'} · 항목 {point.entry_count}개</p><small>{point.reason} · {point.validity === 'VALID' ? '저장 일관성 검증됨' : '검증 확인 필요'}</small></div>
      <Button variant="outline" disabled={busy || !point.can_restore || point.validity !== 'VALID'} onClick={() => inspect(point)}>변경 미리보기 · 복구</Button>
    </div>)}
    {data && data.points.length === 0 && <p>사용할 수 있는 복구 지점이 없어요. 누락·손상된 지점은 복구에 사용하지 않아요.</p>}
    {data && !data.run_ended && <p className="faint-note">작업 완료 뒤 저장할 수 있어요. 실행 중에는 복구할 수 없으며, 복구 전에 세션을 종료해야 해요.</p>}
    {data?.last_save_error && <p className="danger-text">최근 자동 저장 보류: {data.last_save_error}</p>}
    <p className="faint-note">{data?.limitation}</p>
    {error && <p className="danger-text" role="alert">{error}</p>}
    {Boolean(data?.history.length) && <details><summary>복구 이력 {data?.history.length}건</summary>
      {data?.history.map((item, index) => <p key={`${item.saved_at}:${index}`}>{item.saved_at ? new Date(item.saved_at).toLocaleString('ko-KR') : '시각 확인 불가'} · {data.points.find(point => point.checkpoint_id === item.checkpoint_id)?.name ?? '기준점'} · {item.verification !== 'VALID' ? '기록 검증 실패' : `${item.recovery_status === 'RESTORED' ? '복원 완료' : '복원 결과 확인 필요'} / ${item.integrity_status === 'VERIFIED' ? '무결성 검증 완료' : '무결성 확인 필요'}`}</p>)}
    </details>}
    {preview && <RestoreDialog runId={runId} recovery={preview} onClose={() => setPreview(null)} onDone={value => { setPreview(null); setOutcome(value); load() }} />}
    {outcome && <RestoreComplete outcome={outcome} onBack={() => setOutcome(null)} onHome={() => setOutcome(null)} />}
  </section>
}
