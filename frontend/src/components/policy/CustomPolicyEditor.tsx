import { useEffect, useState } from 'react'
import { apiGet, apiPost } from '../../api/client'
import { Button } from '../common/Button'
import { EFFECTS, OPS, type PolicyDocument, type PolicyRule } from './policyModel'
import { readCustomPolicy, writeCustomPolicy } from './policyStorage'
import { Icon } from '../common/Icon'
import { makeRule, RULE_STARTERS, ruleEffects, rulePresentation } from './policyPresentation'

export function CustomPolicyEditor({ onSaved }: { onSaved: () => void }) {
  const stored = readCustomPolicy()
  const [draft, setDraft] = useState<PolicyDocument | null>(stored?.document ?? null)
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState('')
  const [ack, setAck] = useState(false)
  const [saved, setSaved] = useState(Boolean(stored))
  const [target, setTarget] = useState('.env')
  const [operation, setOperation] = useState('READ')
  const [starter, setStarter] = useState('folder')
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
      // Save each revision to a new immutable-source file. Existing policies
      // and active session snapshots are never overwritten by this editor.
      const revision = { ...draft, policy_id: `aia-user-${crypto.randomUUID()}` }
      await apiPost('/api/policy/validate', { document: revision })
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
      setNotice(result.policy_decision === 'INDETERMINATE'
        ? '판단 보류: 규칙 충돌 또는 판단 정보 부족이에요. 대상과 고급 설정의 우선순위를 확인해 주세요. 실제로 실행하지 않았어요.'
        : `저장된 정책의 미리보기: ${result.operation_effect ? EFFECTS[result.operation_effect] : '미확정'} (실행하지 않음)`)
    } catch (failure) { setNotice(String(failure)) }
  }
  if (!draft) return <p role="status">{notice || '사용자 지정 규칙을 준비하는 중…'}</p>
  return <section className="glass policy-facts custom-policy" aria-label="사용자 지정 정책 편집">
    <header className="custom-policy-head"><div><h2>나에게 맞는 보호 규칙</h2>
      <p>보호할 대상과 처리 방식을 골라요. 처음에는 표준 보호의 규칙으로 시작하며, 저장한 설정은 다음 실행부터 적용돼요.</p></div>
      <span className="badge is-neutral">{draft.rules.length}개 규칙 · {saved ? '저장됨' : '저장 전'}</span></header>
    <div className="custom-policy-guide"><span><strong>허용</strong> 작업을 진행해요</span><span><strong>허용하고 기록</strong> 진행하면서 정책 기록을 남겨요</span><span><strong>금지</strong> 정책 위반으로 판단해요</span></div>
    <p className="faint-note">명령 사전 차단은 지원되는 Hook에서만 가능해요. 파일 규칙이 모든 파일 접근을 운영체제 수준에서 차단하는 것은 아니에요.</p>
    <fieldset className="custom-policy-form" disabled={busy}>
    <legend className="sr-only">보호 규칙 설정</legend>
    <label className="custom-default">목록에 없는 작업은 어떻게 할까요? <select className="glass-input" value={draft.default_effect} onChange={event => change({ ...draft, default_effect: event.target.value })}>
      {Object.entries(EFFECTS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
    </select></label>
    <div className="custom-rule-list">
    {draft.rules.map((rule, index) => {
      const info = rulePresentation(rule)
      return <details className="custom-rule" key={rule.rule_id}>
      <summary><span className="custom-rule-icon"><Icon name={info.icon} size={22} /></span>
        <span className="custom-rule-heading"><strong>{info.title}</strong><span>{info.description}</span></span>
        <span className="custom-rule-effects">{ruleEffects(rule).map(({ effect, operations }) => <span key={effect} className={`badge ${effect === 'DENY' ? 'is-danger' : effect === 'AUDIT' ? 'is-warning' : 'is-neutral'}`}>{operations.map(op => OPS[op] ?? op).join('·')} {effect === 'AUDIT' ? '허용·기록' : EFFECTS[effect]}</span>)}</span>
        <Icon name="arrowRight" size={16} />
      </summary>
      <div className="custom-rule-fields">
        <h3>이 대상에 어떤 작업을 허용할까요?</h3>
        {rule.path_patterns?.length === 1 && info.title === '직접 지정한 파일·폴더' && <label>보호할 파일·폴더 경로<input className="glass-input" value={rule.path_patterns[0]} onChange={event => changeRule(index, { ...rule, path_patterns: [event.target.value] })} /><span className="faint-note">예: notes.txt는 파일 하나, documents/**는 폴더 안 파일에 적용해요.</span></label>}
        <div className="custom-effects">{Object.entries(OPS).filter(([op]) => rule.command_patterns ? op === 'EXECUTE' : op !== 'EXECUTE').map(([op, label]) => <label key={op}>{label}<select className="glass-input" value={rule.operation_effects[op] ?? ''} onChange={event => {
          const effects = { ...rule.operation_effects }; if (event.target.value) effects[op] = event.target.value; else delete effects[op]
          changeRule(index, { ...rule, operation_effects: effects })
        }}><option value="">다른 규칙·기본 설정 따르기</option>{Object.entries(EFFECTS).map(([value, name]) => <option value={value} key={value}>{name}</option>)}</select></label>)}</div>
        <p className="faint-note">지정하지 않은 작업은 다른 일치 규칙 또는 기본 설정으로 판단해요. 저장 후 아래에서 결과를 확인할 수 있어요.</p>
        <details className="custom-rule-advanced"><summary>대상·우선순위 고급 설정</summary>
        <div className="custom-rule-fields">
        <label>대상 종류<select className="glass-input" value={rule.command_patterns ? 'command' : 'path'} onChange={event => {
          const { path_patterns: paths, command_patterns: commands, ...rest } = rule
          changeRule(index, { ...rest, ...(event.target.value === 'command' ? { command_patterns: paths ?? commands ?? ['*'], operation_effects: { EXECUTE: 'DENY' } } : { path_patterns: commands ?? paths ?? ['*'], operation_effects: { MODIFY: 'DENY' } }) })
        }}><option value="path">파일 경로</option><option value="command">명령</option></select></label>
        <label>{rule.command_patterns ? '어떤 명령에 적용할까요?' : '어떤 파일·폴더에 적용할까요?'}<textarea className="glass-input is-mono" placeholder={rule.command_patterns ? '예: git reset --hard*' : '예: protected/**'} value={(rule.path_patterns ?? rule.command_patterns ?? []).join('\n')} onChange={event => changeRule(index, { ...rule, ...(rule.command_patterns ? { command_patterns: event.target.value.split('\n') } : { path_patterns: event.target.value.split('\n') }) })} /></label>
        <p className="faint-note">한 줄에 하나씩 입력해요. *는 여러 글자와 일치해요. 파일 경로는 작업공간 기준으로 적어요. 명령 패턴은 모든 변형을 알아내지는 못해요.</p>
        <label>규칙 우선순위<input className="glass-input" type="number" step="1" value={rule.priority} onChange={event => changeRule(index, { ...rule, priority: Number(event.target.value) })} /></label>
        <p className="faint-note">같은 대상에 여러 규칙이 맞으면 큰 숫자가 우선해요. 같은 우선순위에서 허용·금지가 충돌하면 판단이 보류될 수 있어요.</p>
        <small className="faint-note">규칙 식별자: {rule.rule_id}</small>
        </div></details>
        <Button variant="text" className="is-danger" onClick={() => change({ ...draft, rules: draft.rules.filter((_, current) => current !== index) })}>이 규칙 제거</Button>
      </div>
    </details>})}
    </div>
    <div className="custom-add-rule"><label>새로 보호할 대상<select className="glass-input" value={starter} onChange={event => setStarter(event.target.value)}>{RULE_STARTERS.map(item => <option key={item.key} value={item.key}>{item.label}</option>)}</select></label>
      <Button variant="secondary" onClick={() => change({ ...draft, rules: [...draft.rules, makeRule(starter, `user-${crypto.randomUUID()}`)] })}><Icon name="plus" size={16} />규칙 추가</Button></div>
    <div className="glass-notice is-warning"><p>금지를 허용으로 바꾸거나 규칙을 제거하면 보호가 약해질 수 있어요. 패턴에 맞지 않는 명령 변형은 다른 결과가 나올 수 있어요. 비밀값 자체를 검사하는 설정은 아니에요.</p></div>
    <label className="restore-ack"><input type="checkbox" checked={ack} onChange={event => setAck(event.target.checked)} />보호 범위를 확인했으며 다음 실행에 적용되는 것을 이해했어요.</label>
    <Button variant="cta" disabled={!ack || busy} onClick={save}>{busy ? '검증·저장 중…' : '규칙 검증하고 저장'}</Button>
    <h3>저장한 규칙을 시험해 보세요</h3>
    <p className="faint-note">아래에 파일이나 명령을 넣으면 허용·기록·금지 중 어떤 결과인지 확인해요. 실제 작업은 실행하지 않아요.</p>
    <div className="policy-preview-form">
      <select className="glass-input" aria-label="미리보기 행동" value={operation} onChange={event => setOperation(event.target.value)}>{Object.entries(OPS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select>
      <input className="glass-input" aria-label="미리보기 경로 또는 명령" value={target} onChange={event => setTarget(event.target.value)} />
      <Button variant="secondary" disabled={!saved || busy} onClick={preview}>저장된 규칙 판정 보기</Button>
    </div>
    </fieldset>
    {notice && <p role="status">{notice}</p>}
  </section>
}
