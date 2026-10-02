import { useState } from 'react'
import { apiPost } from '../../api/client'
import { displayStatus, TEMPLATE_NAMES } from '../../api/display'
export function PolicyPreview({ profile }: { profile: string | null }) {
  const [operation, setOperation] = useState('READ')
  const [target, setTarget] = useState('.env')
  const [result, setResult] = useState<Record<string, unknown> | null>(null)
  const [comparison, setComparison] = useState<Array<Record<string, unknown>>>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  async function preview() {
    if (!profile || !target.trim() || busy) return
    setBusy(true); setError(null); setResult(null); setComparison([])
    try { setResult(await apiPost('/api/policy/preview', { policy_profile: profile, operation, ...(operation === 'EXECUTE' ? { command: target } : { path: target }) })) }
    catch (failure) { setError(failure instanceof Error ? failure.message : String(failure)) }
    finally { setBusy(false) }
  }
  async function compare() {
    if (!target.trim() || busy) return
    setBusy(true); setError(null); setResult(null); setComparison([])
    try {
      setComparison(await Promise.all(Object.keys(TEMPLATE_NAMES).map(policy_profile =>
        apiPost<Record<string, unknown>>('/api/policy/preview', { policy_profile, operation, ...(operation === 'EXECUTE' ? { command: target } : { path: target }) })
      )))
    } catch (failure) { setError(failure instanceof Error ? failure.message : String(failure)) }
    finally { setBusy(false) }
  }
  return <section className="soft-card data-section policy-preview"><h3>실행 없이 정책 확인</h3><p>선택한 정책으로 경로나 명령을 판정합니다. 에이전트를 실행하거나 파일을 읽지 않습니다.</p><div className="policy-preview-form"><select aria-label="검토할 행위" value={operation} onChange={event => { setOperation(event.target.value); setResult(null); setComparison([]) }}>{['READ','MODIFY','DELETE','EXECUTE'].map(value => <option key={value} value={value}>{displayStatus(value)}</option>)}</select><input aria-label="검토할 경로 또는 명령" value={target} onChange={event => { setTarget(event.target.value); setResult(null); setComparison([]) }} placeholder={operation === 'EXECUTE' ? '검토할 명령' : '검토할 상대 경로'} /><button type="button" className="secondary-action" disabled={!profile || busy || !target.trim()} onClick={preview}>{busy ? '확인 중…' : '판정 확인'}</button></div><button type="button" className="text-action" disabled={busy || !target.trim()} onClick={compare}>같은 행위로 다른 템플릿과 비교</button>{comparison.length > 0 && <div className="policy-comparison" role="table" aria-label="실제 정책 판정 비교">{comparison.map(item => <div role="row" key={String(item.profile)}><b role="cell">{TEMPLATE_NAMES[String(item.profile)]}</b><span role="cell">{displayStatus(String(item.policy_decision))} · {displayStatus(String(item.operation_effect))}</span></div>)}<p>입력한 한 행위에 대한 실제 판정입니다. 정책 전체의 강약 순위를 의미하지 않습니다.</p></div>}{error && <p role="alert">{error}</p>}{result && <div className="validation-note" role="status"><b>{displayStatus(String(result.policy_decision ?? ''))} · {displayStatus(String(result.operation_effect ?? ''))}</b><p>적용 정책 {String(result.policy_id ?? '')} · 규칙 {Array.isArray(result.matched_rule_ids) ? result.matched_rule_ids.join(', ') || '일반 규칙' : '확인 전'}</p><span>이 결과는 정책 미리보기입니다. 실제 실행 허가나 차단 성공의 증거가 아닙니다.</span></div>}</section>
}
