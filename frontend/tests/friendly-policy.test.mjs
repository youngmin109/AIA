import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { POLICY_ICONS, makeRule, ruleEffects, rulePresentation } from '../src/components/policy/policyPresentation.ts'

test('all built-in rules get readable names without changing stored rule documents', () => {
  for (const file of ['보호-우선-개발형.ko.json', '기본-개발형.ko.json', '보수적-보안형.ko.json', '자유-개발형.ko.json']) {
    const document = JSON.parse(readFileSync(new URL('../../policies/profiles/' + file, import.meta.url), 'utf8'))
    for (const raw of document.규칙) {
      const rule = { rule_id: raw.규칙ID, path_patterns: raw.경로패턴, command_patterns: raw.명령패턴, operation_effects: {} }
      const before = JSON.stringify(rule)
      const presentation = rulePresentation(rule)
      assert.doesNotMatch(presentation.title, /직접 지정|\*/)
      assert.ok(presentation.description)
      assert.equal(JSON.stringify(rule), before)
    }
  }
})

test('editing a known rule target does not preserve a misleading friendly name', () => {
  const rule = { rule_id: 'protected-secret-files', path_patterns: ['*.txt'], operation_effects: { READ: 'ALLOW' } }
  assert.equal(rulePresentation(rule).title, '직접 지정한 파일·폴더')
  assert.equal(rulePresentation({ ...rule, path_patterns: undefined, command_patterns: ['echo hello'] }).title, '직접 지정한 명령')
})

test('effect summaries show actual configured actions, including weakened rules', () => {
  const rule = makeRule('secret', 'test')
  rule.operation_effects.READ = 'ALLOW'
  const summary = ruleEffects(rule)
  assert.deepEqual(summary.find(item => item.effect === 'ALLOW').operations, ['READ'])
  assert.equal(summary.find(item => item.effect === 'DENY').operations.includes('READ'), false)
})

test('rule starters are isolated copies and standard/custom icons differ', () => {
  const first = makeRule('secret', 'one')
  first.path_patterns.push('extra')
  first.operation_effects.READ = 'ALLOW'
  const second = makeRule('secret', 'two')
  assert.equal(second.path_patterns.includes('extra'), false)
  assert.equal(second.operation_effects.READ, 'DENY')
  assert.notEqual(POLICY_ICONS.PROTECTED_DEVELOPMENT, POLICY_ICONS.CUSTOM)
})

test('advanced syntax is folded away and validation and save use the same revision', () => {
  const source = readFileSync(new URL('../src/components/policy/CustomPolicyEditor.tsx', import.meta.url), 'utf8')
  assert.match(source, /<details className="custom-rule-advanced"><summary>대상·우선순위 고급 설정/)
  assert.match(source, /\/api\/policy\/validate', \{ document: revision \}/)
  assert.match(source, /\/api\/policy\/save', \{ document: revision \}/)
  assert.match(source, /fieldset className="custom-policy-form" disabled=\{busy\}/)
})
