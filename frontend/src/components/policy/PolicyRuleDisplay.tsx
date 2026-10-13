import { Icon } from '../common/Icon'
import { EFFECTS, OPS, type PolicyRule } from './policyModel'
import { ruleEffects, rulePresentation } from './policyPresentation'

/** Shared presentation only: editable and built-in policies use identical names and effects. */
export function PolicyRuleSummary({ rule }: { rule: PolicyRule }) {
  const info = rulePresentation(rule)
  return <summary><span className="custom-rule-icon"><Icon name={info.icon} size={22} /></span>
    <span className="custom-rule-heading"><strong>{info.title}</strong><span>{info.description}</span></span>
    <span className="custom-rule-effects">{ruleEffects(rule).map(({ effect, operations }) => <span key={effect} className={`badge ${effect === 'DENY' ? 'is-danger' : effect === 'AUDIT' ? 'is-warning' : 'is-neutral'}`}>{operations.map(op => OPS[op] ?? op).join('·')} {effect === 'AUDIT' ? '허용·기록' : EFFECTS[effect]}</span>)}</span>
    <Icon name="arrowRight" size={16} />
  </summary>
}

export function PolicyEffectGuide() {
  return <><div className="custom-policy-guide"><span><strong>허용</strong> 작업을 진행해요</span><span><strong>허용하고 기록</strong> 진행하면서 정책 기록을 남겨요</span><span><strong>금지</strong> 정책 위반으로 판단해요</span></div>
    <p className="faint-note">명령 사전 차단은 지원되는 Hook에서만 가능해요. 파일 규칙이 모든 파일 접근을 운영체제 수준에서 차단하는 것은 아니에요.</p></>
}
