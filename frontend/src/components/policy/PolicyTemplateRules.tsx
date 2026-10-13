import { useEffect, useState } from 'react'
import { apiGet } from '../../api/client'
import type { PolicyProfile } from '../../api/endpoints'
import { Button } from '../common/Button'
import { EFFECTS, OPS, type PolicyDocument } from './policyModel'
import { PolicyEffectGuide, PolicyRuleSummary } from './PolicyRuleDisplay'

/** Read the same template the engine uses. Built-in rules are never editable here. */
export function PolicyTemplateRules({ profile }: { profile: PolicyProfile }) {
  const [result, setResult] = useState<{ profile: string; retry: number; document: PolicyDocument | null; error: boolean } | null>(null)
  const [retry, setRetry] = useState(0)
  const current = result?.profile === profile.value && result.retry === retry ? result : null
  const document = current?.document
  const error = current?.error
  useEffect(() => {
    let cancelled = false
    apiGet<{ document: PolicyDocument }>(`/api/policy/templates/${encodeURIComponent(profile.value)}`)
      .then(response => { if (!cancelled) setResult({ profile: profile.value, retry, document: response.document, error: false }) })
      .catch(() => { if (!cancelled) setResult({ profile: profile.value, retry, document: null, error: true }) })
    return () => { cancelled = true }
  }, [profile.value, retry])

  return <section className="glass policy-facts custom-policy" aria-label={`${profile.display_name} 보호 규칙`}>
    <header className="custom-policy-head"><div><h2>{profile.display_name} · 보호 규칙</h2><p>{profile.description}</p></div>
      <span className="badge is-neutral">기본 모드 · 읽기 전용{document ? ` · ${document.rules.length}개 규칙` : ''}</span></header>
    <PolicyEffectGuide />
    <p className="faint-note">기본 모드의 규칙은 정해져 있어요. 내 작업에 맞게 바꾸려면 위에서 사용자 지정을 선택하세요. 실행 중인 정책은 바뀌지 않아요.</p>
    {error ? <div className="glass-notice is-warning" role="alert"><p>규칙을 불러오지 못했어요. 아직 보호 대상과 처리 방식을 확인할 수 없어요.</p><Button variant="secondary" onClick={() => setRetry(value => value + 1)}>다시 불러오기</Button></div>
      : !document ? <p role="status">보호 규칙을 불러오는 중이에요…</p> : <>
        <div className="policy-template-default"><strong>목록에 없는 작업</strong><span>{EFFECTS[document.default_effect] ?? '확인 필요'}</span></div>
        <div className="custom-rule-list">{document.rules.map(rule => <details className="custom-rule" key={rule.rule_id}>
          <PolicyRuleSummary rule={rule} />
          <div className="custom-rule-fields"><h3>이 대상에는 이렇게 적용돼요</h3>
            <dl className="policy-operation-list">{Object.entries(OPS).filter(([op]) => rule.command_patterns ? op === 'EXECUTE' : op !== 'EXECUTE').map(([op, label]) => <div key={op}><dt>{label}</dt><dd>{EFFECTS[rule.operation_effects[op]] ?? '다른 규칙·기본 설정 따르기'}</dd></div>)}</dl>
            <details className="custom-rule-advanced"><summary>적용 대상 자세히 보기</summary><div className="custom-rule-fields">
              <p className="faint-note">{rule.command_patterns ? '등록된 명령 패턴에 적용해요. 모든 명령 변형을 알아내는 것은 아니에요.' : '작업공간 기준의 파일 경로 패턴에 적용해요. 비밀값 자체를 검사하는 것은 아니에요.'}</p>
              <pre className="policy-target-patterns">{(rule.command_patterns ?? rule.path_patterns ?? []).join('\n')}</pre>
              <p className="faint-note">규칙 우선순위: {rule.priority} · 같은 대상에서는 큰 숫자가 우선해요.</p>
            </div></details>
          </div>
        </details>)}</div>
      </>}
  </section>
}
