import { useState } from 'react'
import { Button } from '../common/Button'
import { apiPost } from '../../api/client'
import { displayStatus } from '../../api/display'
import type { PolicyProfile } from '../../api/endpoints'

const OPERATIONS: Array<[string, string]> = [['READ', '읽기'], ['MODIFY', '수정'], ['DELETE', '삭제'], ['EXECUTE', '실행']]
const EFFECT_TONE: Record<string, string> = { DENY: 'is-danger', AUDIT: 'is-warning', ALLOW: 'is-success' }
const EFFECT_LABEL: Record<string, string> = { DENY: '차단', AUDIT: '기록', ALLOW: '허용' }

type Preview = Record<string, unknown>

/** Dry-run of the policy engine for one action. It never runs the command or reads the file. */
export function PolicyPreview({ profile, profiles }: { profile: string | null; profiles: PolicyProfile[] }) {
  const [operation, setOperation] = useState('EXECUTE')
  const [target, setTarget] = useState('rm -rf data/')
  const [results, setResults] = useState<Preview[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const selected = results.find(item => String(item.profile) === profile)

  function reset(next: () => void) {
    next()
    setResults([])
    setError(null)
  }

  async function preview() {
    if (!target.trim() || busy || profiles.length === 0) return
    setBusy(true)
    setError(null)
    try {
      setResults(await Promise.all(profiles.map(({ value: policy_profile }) =>
        apiPost<Preview>('/api/policy/preview', { policy_profile, operation, ...(operation === 'EXECUTE' ? { command: target } : { path: target }) }),
      )))
    } catch (failure) {
      setResults([])
      setError(failure instanceof Error ? failure.message : String(failure))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="glass policy-preview" aria-labelledby="policy-preview-title">
      <h2 id="policy-preview-title">이 명령은 어떻게 판정될까?</h2>
      <form className="policy-preview-form" onSubmit={event => { event.preventDefault(); preview() }}>
        <div className="segmented" role="group" aria-label="행동 종류">
          {OPERATIONS.map(([value, label]) => (
            <button key={value} type="button" aria-pressed={operation === value} onClick={() => reset(() => setOperation(value))}>{label}</button>
          ))}
        </div>
        <label className="visually-hidden" htmlFor="policy-preview-target">{operation === 'EXECUTE' ? '확인할 명령' : '확인할 경로'}</label>
        <input id="policy-preview-target" className="glass-input is-mono policy-preview-input" value={target} onChange={event => reset(() => setTarget(event.target.value))} placeholder={operation === 'EXECUTE' ? '확인할 명령' : '확인할 상대 경로 (예: .env)'} spellCheck={false} />
        <Button variant="cta" type="submit" disabled={busy || !target.trim() || profiles.length === 0}>{busy ? '확인 중…' : '판정 보기'}</Button>
      </form>
      {results.length > 0 && (
        <div className="policy-results" role="table" aria-label="정책별 판정">
          {results.map(item => {
            const effect = String(item.operation_effect ?? '')
            const name = profiles.find(candidate => candidate.value === String(item.profile))?.display_name ?? String(item.profile)
            return (
              <div role="row" key={String(item.profile)} className={`policy-result ${EFFECT_TONE[effect] ?? ''}${String(item.profile) === profile ? ' is-current' : ''}`}>
                <span role="cell">{name}{String(item.profile) === profile && <small> · 사용 중</small>}</span>
                <strong role="cell">{EFFECT_LABEL[effect] ?? displayStatus(effect)}</strong>
              </div>
            )
          })}
        </div>
      )}
      {selected && (
        <p className="faint-note">사용 중인 정책 판정 {displayStatus(String(selected.policy_decision ?? ''))} · 규칙 {Array.isArray(selected.matched_rule_ids) ? selected.matched_rule_ids.join(', ') || '일반 규칙' : '확인 전'}</p>
      )}
      {error && <p className="danger-text" role="alert">{error}</p>}
      <p className="faint-note">미리보기는 판정만 보여줘요. 명령을 실행하거나 파일을 읽지 않고, 실제 실행 허가나 차단 성공의 증거도 아니에요.</p>
    </section>
  )
}
