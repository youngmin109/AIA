import { useEffect, useState } from 'react'
import { apiGet, apiPost } from '../../api/client'
import { Button } from '../common/Button'
import { EFFECTS, OPS, type PolicyDocument, type PolicyRule } from './policyModel'
import { readCustomPolicy, writeCustomPolicy } from './policyStorage'

export function CustomPolicyEditor({ onSaved }: { onSaved: () => void }) {
  const stored = readCustomPolicy()
  const [draft, setDraft] = useState<PolicyDocument | null>(stored?.document ?? null)
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState('')
  const [ack, setAck] = useState(false)
  const [saved, setSaved] = useState(Boolean(stored))
  const [target, setTarget] = useState('.env')
  const [operation, setOperation] = useState('READ')
  useEffect(() => {
    if (stored) return
    let cancelled = false
    apiGet<{ document: PolicyDocument }>('/api/policy/templates/PROTECTED_DEVELOPMENT').then(({ document }) => {
      if (!cancelled) setDraft({ ...document, profile: 'CUSTOM', policy_id: `aia-user-${crypto.randomUUID()}`, policy_version: '1' })
    }).catch(() => { if (!cancelled) setNotice('기본 규칙을 불러오지 못했어요. 다시 열어 주세요.') })
    return () => { cancelled = true }
    // Load only on mount. Subsequent edits remain in this draft.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function change(next: PolicyDocument) { setDraft(next); setSaved(false); setAck(false); setNotice('변경한 규칙은 아직 저장되지 않았어요.') }
  function changeRule(index: number, next: PolicyRule) {
    if (draft) change({ ...draft, rules: draft.rules.map((rule, current) => current === index ? next : rule) })
  }
  async function save() {
    if (!draft || !ack || busy) return
    setBusy(true)
    try {
      await apiPost('/api/policy/validate', { document: draft })
      // Save each revision to a new immutable-source file. Existing policies
      // and active session snapshots are never overwritten by this editor.
      const revision = { ...draft, policy_id: `aia-user-${crypto.randomUUID()}` }
      const result = await apiPost<{ path: string }>('/api/policy/save', { document: revision })
      writeCustomPolicy({ path: result.path, document: revision })
      setDraft(revision); setSaved(true); setNotice('검증하고 저장했어요. 새 보호 실행에서 사용자 지정을 선택하세요.'); onSaved()
    } catch (failure) { setNotice(`저장하지 못했어요: ${failure instanceof Error ? failure.message : String(failure)}`) }
    finally { setBusy(false) }
  }
  async function preview() {
    const policy = readCustomPolicy()
    if (!saved || !policy || !target.trim()) return
    try {
      const result = await apiPost<{ operation_effect?: string; policy_decision: string }>('/api/policy/preview', {
        policy_profile: 'CUSTOM', custom_policy_path: policy.path, operation,
        ...(operation === 'EXECUTE' ? { command: target } : { path: target }),
      })
      setNotice(`저장된 정책의 미리보기: ${result.operation_effect ? EFFECTS[result.operation_effect] : '미확정'} (실행하지 않음)`)
    } catch (failure) { setNotice(String(failure)) }
  }
  if (!draft) return <p role="status">{notice || '사용자 지정 규칙을 준비하는 중…'}</p>
  return <section className="glass policy-facts custom-policy" aria-label="사용자 지정 정책 편집">
    <h2>사용자 지정 · 세부 규칙</h2>
    <p>표준 보호를 바탕으로 시작해요. 경로와 명령 패턴, 우선순위, 행동별 효과를 직접 바꿀 수 있어요.</p>
    <label>일치하는 규칙이 없을 때 <select className="glass-input" value={draft.default_effect} onChange={event => change({ ...draft, default_effect: event.target.value })}>
      {Object.entries(EFFECTS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
    </select></label>
    {draft.rules.map((rule, index) => <details key={rule.rule_id}>
      <summary>{(rule.path_patterns ?? rule.command_patterns)?.join(' · ') || '대상을 입력해 주세요'}</summary>
      <div className="custom-rule-fields">
        <label>대상 종류<select className="glass-input" value={rule.command_patterns ? 'command' : 'path'} onChange={event => {
          const { path_patterns: paths, command_patterns: commands, ...rest } = rule
          changeRule(index, { ...rest, ...(event.target.value === 'command' ? { command_patterns: paths ?? commands ?? ['*'], operation_effects: { EXECUTE: 'DENY' } } : { path_patterns: commands ?? paths ?? ['*'], operation_effects: { MODIFY: 'DENY' } }) })
        }}><option value="path">파일 경로</option><option value="command">명령</option></select></label>
        <label>패턴 (한 줄에 하나)<textarea className="glass-input is-mono" value={(rule.path_patterns ?? rule.command_patterns ?? []).join('\n')} onChange={event => changeRule(index, { ...rule, ...(rule.command_patterns ? { command_patterns: event.target.value.split('\n') } : { path_patterns: event.target.value.split('\n') }) })} /></label>
        <label>우선순위<input className="glass-input" type="number" value={rule.priority} onChange={event => changeRule(index, { ...rule, priority: Number(event.target.value) })} /></label>
        <div className="custom-effects">{Object.entries(OPS).filter(([op]) => rule.command_patterns ? op === 'EXECUTE' : op !== 'EXECUTE').map(([op, label]) => <label key={op}>{label}<select className="glass-input" value={rule.operation_effects[op] ?? ''} onChange={event => {
          const effects = { ...rule.operation_effects }; if (event.target.value) effects[op] = event.target.value; else delete effects[op]
          changeRule(index, { ...rule, operation_effects: effects })
        }}><option value="">이 규칙에서 지정 안 함</option>{Object.entries(EFFECTS).map(([value, name]) => <option value={value} key={value}>{name}</option>)}</select></label>)}</div>
        <Button variant="text" className="is-danger" onClick={() => change({ ...draft, rules: draft.rules.filter((_, current) => current !== index) })}>이 규칙 제거</Button>
      </div>
    </details>)}
    <Button variant="secondary" onClick={() => change({ ...draft, rules: [...draft.rules, { rule_id: `user-${crypto.randomUUID()}`, asset_type: 'WORKSPACE', priority: 1100, path_patterns: ['protected/**'], operation_effects: { DELETE: 'DENY', MODIFY: 'AUDIT' } }] })}>경로·명령 규칙 추가</Button>
    <div className="glass-notice is-warning"><p>금지를 허용으로 바꾸거나 규칙을 제거하면 보호가 약해질 수 있어요. 패턴에 맞지 않는 명령 변형은 다른 결과가 나올 수 있어요. 비밀값 자체를 검사하는 설정은 아니에요.</p></div>
    <label className="restore-ack"><input type="checkbox" checked={ack} onChange={event => setAck(event.target.checked)} />보호 범위를 확인했으며 다음 실행에 적용되는 것을 이해했어요.</label>
    <Button variant="cta" disabled={!ack || busy} onClick={save}>{busy ? '검증·저장 중…' : '규칙 검증하고 저장'}</Button>
    <div className="policy-preview-form">
      <select className="glass-input" aria-label="미리보기 행동" value={operation} onChange={event => setOperation(event.target.value)}>{Object.entries(OPS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select>
      <input className="glass-input" aria-label="미리보기 경로 또는 명령" value={target} onChange={event => setTarget(event.target.value)} />
      <Button variant="secondary" disabled={!saved || busy} onClick={preview}>저장된 규칙 판정 보기</Button>
    </div>
    {notice && <p role="status">{notice}</p>}
  </section>
}
