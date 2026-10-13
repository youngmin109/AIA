import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { effectBadge, effectTone, ruleCardClass } from '../src/components/policy/policyPresentation.ts'
const css = name => readFileSync(new URL('../src/styles/' + name, import.meta.url), 'utf8')

test('every effect badge uses a badge color that the stylesheet defines', () => {
  const glass = css('glass.css')
  for (const effect of ['ALLOW', 'AUDIT', 'DENY', 'UNKNOWN', undefined]) {
    const tone = effectBadge(effect).split(' ')[1]
    assert.match(glass, new RegExp(`\\.badge\\.${tone} \\{`), `${effect} → ${tone}`)
  }
})

test('rule cards take the color of their strictest effect', () => {
  const rule = effects => ({ rule_id: 'r', priority: 1, asset_type: 'WORKSPACE', path_patterns: ['a'], operation_effects: effects })
  assert.equal(ruleCardClass(rule({ READ: 'ALLOW', MODIFY: 'AUDIT', DELETE: 'DENY' })), 'custom-rule is-deny')
  assert.equal(ruleCardClass(rule({ READ: 'ALLOW', MODIFY: 'AUDIT' })), 'custom-rule is-audit')
  assert.equal(ruleCardClass(rule({ READ: 'ALLOW' })), 'custom-rule is-allow')
  assert.equal(ruleCardClass(rule({})), 'custom-rule')
  const manage = css('manage.css')
  for (const effect of ['ALLOW', 'AUDIT', 'DENY']) {
    assert.match(manage, new RegExp(`\\.custom-rule\\.${effectTone(effect)} \\{`))
    assert.match(manage, new RegExp(`\\.policy-operation-list > \\.${effectTone(effect)} \\{`))
  }
})
