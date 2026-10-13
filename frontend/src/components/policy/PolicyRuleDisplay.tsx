import { GlossyIcon, type GlossTone } from '../common/Glass'
import { Icon, type IconName } from '../common/Icon'
import { EFFECTS, OPS, type PolicyRule } from './policyModel'
import { EFFECT_LOOK, effectBadge, ruleEffects, rulePresentation } from './policyPresentation'

// The icon tile color says what a rule targets; badges and the card edge say how it is handled.
const TARGET_TONE: Partial<Record<IconName, GlossTone>> = { terminal: 'hook', block: 'process', lock: 'amber', file: 'file', folder: 'success' }

/** Shared presentation only: editable and built-in policies use identical names and effects. */
export function PolicyRuleSummary({ rule }: { rule: PolicyRule }) {
  const info = rulePresentation(rule)
  return <summary><GlossyIcon tone={TARGET_TONE[info.icon] ?? 'accent'} icon={info.icon} />
    <span className="custom-rule-heading"><strong>{info.title}</strong><span>{info.description}</span></span>
    <span className="custom-rule-effects">{ruleEffects(rule).map(({ effect, operations }) => <span key={effect} className={effectBadge(effect)}><Icon name={EFFECT_LOOK[effect]?.icon ?? 'info'} size={13} />{operations.map(op => OPS[op] ?? op).join('·')} {effect === 'AUDIT' ? '허용·기록' : EFFECTS[effect]}</span>)}</span>
    <Icon name="arrowRight" size={16} />
  </summary>
}

export function PolicyEffectGuide() {
  return <><div className="custom-policy-guide">
      <span className="is-allow"><strong><Icon name="check" size={14} />허용</strong> 작업을 진행해요</span>
      <span className="is-audit"><strong><Icon name="records" size={14} />허용하고 기록</strong> 진행하면서 정책 기록을 남겨요</span>
      <span className="is-deny"><strong><Icon name="block" size={14} />금지</strong> 정책 위반으로 판단해요</span>
    </div>
    <p className="policy-note"><Icon name="info" size={16} /><span>명령 사전 차단은 지원되는 Hook에서만 가능해요. 파일 규칙이 모든 파일 접근을 운영체제 수준에서 차단하는 것은 아니에요.</span></p></>
}
