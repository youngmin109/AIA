import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { POLICY_ICONS } from '../src/components/policy/policyPresentation.ts'
const source = name => readFileSync(new URL('../src/' + name, import.meta.url), 'utf8')

test('setup and policy views use the same custom icon', () => {
  assert.equal(POLICY_ICONS.CUSTOM, 'settings')
  for (const file of ['components/policy/PolicyView.tsx', 'components/settings/ProtectionSetupModal.tsx']) {
    assert.match(source(file), /POLICY_ICONS\[profile.value\]/)
  }
})

test('all five modes share readable rule and effect presentation', () => {
  for (const file of ['CustomPolicyEditor', 'PolicyTemplateRules']) {
    const component = source(`components/policy/${file}.tsx`)
    assert.match(component, /<PolicyRuleSummary rule=\{rule\}/)
    assert.match(component, /<PolicyEffectGuide/)
  }
  assert.match(source('components/policy/PolicyView.tsx'), /<PolicyTemplateRules/)
  assert.match(source('components/policy/PolicyView.tsx'), /key=\{`rules-\$/)
  assert.match(source('components/policy/PolicyView.tsx'), /key=\{`preview-\$/)
})

test('built-in rule view fetches actual templates and never saves or modifies policies', () => {
  const component = source('components/policy/PolicyTemplateRules.tsx')
  assert.match(component, /\/api\/policy\/templates\//)
  assert.match(component, /EFFECTS\[rule.operation_effects\[op\]\]/)
  assert.match(component, /EFFECTS\[document.default_effect\]/)
  assert.match(component, /읽기 전용/)
  assert.doesNotMatch(component, /apiPost|policy\/save|<select|<input|<textarea/)
  assert.match(component, /cancelled = true/)
  assert.match(component, /규칙을 불러오지 못했어요/)
})

test('logo has a dedicated white circular surface in every color theme', () => {
  assert.match(source('styles/theme.css'), /--brand-surface: #ffffff/)
  const css = source('styles/glass.css').match(/\.rail-logo\s*\{([^}]+)\}/)[1]
  assert.match(css, /border-radius: 50%/)
  assert.match(css, /background: var\(--brand-surface\)/)
})
