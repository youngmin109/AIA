import test from 'node:test'
import assert from 'node:assert/strict'
import { guardianStatus } from '../src/api/guardianStatus.ts'
import { deriveVerdict } from '../src/api/resultVerdict.ts'
import { displayStatus, isSessionRunning } from '../src/api/display.ts'
import { normalizeMotionPreference } from '../src/api/motionPreference.ts'

test('unverified user stop is not a policy violation', () => {
  const value = guardianStatus({ selected: true, ready: true, status: { session: { status: 'ABORTED' } }, result: { session_status: 'ABORTED', bundle_status: 'VALID', protection_state: 'ABORTED_DEGRADED', incidents: [] } })
  assert.equal(value.state, 'review')
  assert.ok(!value.headline.includes('정책 위반'))
})
test('ended session is not live and ending does not imply recovery', () => {
  assert.equal(isSessionRunning('ABORTED'), false)
  const value = guardianStatus({ selected: true, ready: true, status: { session: { status: 'COMPLETED' } }, result: { session_status: 'COMPLETED', bundle_status: 'VALID', protection_state: 'COMPLETED_VERIFIED' } })
  assert.equal(value.state, 'normal')
  assert.ok(!value.label.includes('복구'))
})
test('invalid bundle takes priority over incident count', () => {
  assert.equal(deriveVerdict({ bundle_status: 'INVALID', incident_count: 2 }).branch, 'FAILED_DEGRADED_INVALID')
})
test('record integrity alone is not proof of complete protection', () => {
  assert.notEqual(deriveVerdict({ bundle_status: 'VALID', session_status: 'COMPLETED' }).branch, 'SUCCESS')
  assert.equal(deriveVerdict({ bundle_status: 'VALID', protection_state: 'COMPLETED_DEGRADED' }).tone, 'warn')
})
test('disconnected observation is not reported as healthy', () => {
  assert.equal(guardianStatus({ selected: true, ready: true, error: true }).state, 'review')
  assert.equal(guardianStatus({ selected: false, ready: false }).label, '연결 필요')
})
test('recovery success requires both recovery and integrity', () => {
  const base = { selected: true, ready: true, status: { session: { status: 'COMPLETED' } }, result: { session_status: 'COMPLETED', bundle_status: 'VALID', protection_state: 'COMPLETED_VERIFIED', recovery_status: 'RESTORED' } }
  assert.notEqual(guardianStatus(base).state, 'recovery')
  assert.equal(guardianStatus({ ...base, result: { ...base.result, integrity_status: 'VERIFIED' } }).state, 'recovery')
})
test('labels are friendly', () => {
  assert.equal(displayStatus('HOOK_VERIFICATION_REQUIRED'), '보호 연결 재확인 필요')
})
test('motion follows accessibility preferences by default, with explicit full and reduced modes', () => {
  assert.equal(normalizeMotionPreference(null), 'auto')
  assert.equal(normalizeMotionPreference('invalid'), 'auto')
  assert.equal(normalizeMotionPreference('full'), 'full')
  assert.equal(normalizeMotionPreference('reduced'), 'reduced')
})

test('guardian names an orphaned run instead of waiting for a result that never comes', () => {
  const preparing = guardianStatus({ selected: true, ready: true, status: { session: { status: 'PREPARING' }, runtime_reconciliation: { orphaned: true, agent_process_status: 'NOT_STARTED' } } })
  assert.equal(preparing.label, '준비 중 중단')
  const lost = guardianStatus({ selected: true, ready: true, status: { session: { status: 'RUNNING' }, runtime_reconciliation: { orphaned: true, agent_process_status: 'PROCESS_GONE' } } })
  assert.equal(lost.label, '연결 끊김')
  const finished = guardianStatus({ selected: true, ready: true, status: { session: { status: 'COMPLETED' } } })
  assert.equal(finished.label, '결과 확인 중')
})
