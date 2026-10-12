import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { EFFECTS, OPS } from '../src/components/policy/policyModel.ts'
const source = path => readFileSync(new URL('../src/' + path, import.meta.url), 'utf8')

test('policy explanations keep audit distinct from deny and expose every supported operation', () => {
  assert.equal(EFFECTS.DENY, '금지')
  assert.match(EFFECTS.AUDIT, /허용/)
  assert.equal(Object.keys(OPS).length, 7)
  assert.doesNotMatch(source('components/policy/PolicyView.tsx'), /PolicyDetails|선택한 정책 자세히 보기/)
})

test('policy cards stay on one row and pet has no bottom status card', () => {
  assert.match(source('styles/manage.css'), /grid-template-columns: repeat\(5, minmax\(180px, 1fr\)\)/)
  assert.doesNotMatch(source('components/shell/DesktopGuardian.tsx'), /desktop-guardian-note|desktop-guardian-actions/)
  assert.match(source('components/shell/DesktopGuardian.tsx'), /open_guardian_help/)
  assert.match(source('components/settings/SettingsView.tsx'), /type="range"/)
  assert.match(source('components/shell/Shell.tsx'), /aia:guardian-help/)
})
test('custom policy is selectable and its actual saved path reaches Core', () => {
  const setup = source('components/settings/ProtectionSetupModal.tsx')
  assert.match(setup, /custom_policy_path: customPolicy\?\.path/)
  assert.match(setup, /policyProfile !== 'CUSTOM' \|\| Boolean\(customPolicy\)/)
  assert.match(source('components/policy/CustomPolicyEditor.tsx'), /\/api\/policy\/validate/)
})
test('restore uses selected checkpoint and native pet cannot heartbeat on behalf of main', () => {
  assert.match(source('components/results/WorkspaceRestoreControl.tsx'), /recovery\.preview_fingerprint, recovery\.checkpoint_id/)
  assert.match(source('main.tsx'), /else startDesktopHeartbeat\(\)/)
  assert.match(source('components/shell/DesktopGuardian.tsx'), /최신 상태 확인 불가/)
})

test('the desktop guardian never treats a run left behind by a closed app as live', async () => {
  const { isRunActive } = await import('../src/api/sessionNavigation.ts')
  assert.equal(isRunActive({ session_id: 'a', status: 'RUNNING' }), true)
  assert.equal(isRunActive({ session_id: 'b', status: 'RUNNING', runtime_reconciliation: { orphaned: true } }), false)
  assert.equal(isRunActive({ session_id: 'c', status: 'PREPARING', runtime_reconciliation: { orphaned: true } }), false)
  assert.equal(isRunActive({ session_id: 'd', status: 'COMPLETED' }), false)
})
