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
test('full access is a scope choice, not a degraded failure, when the bundle is valid', () => {
  const fullAccess = { bundle_status: 'VALID', session_status: 'COMPLETED', protection_state: 'COMPLETED_DEGRADED', limitations: ['CODEX_FULL_ACCESS_USER_SELECTED'] }
  assert.equal(deriveVerdict(fullAccess).tone, 'ok')
  assert.ok(deriveVerdict(fullAccess).detail.includes('작업 폴더'))
  // A real failure still warns even under full access.
  assert.equal(deriveVerdict({ ...fullAccess, bundle_status: 'INVALID' }).tone, 'bad')
})
test('threats stopped before they ran read as a protection win, not a review queue', () => {
  const blocked = { bundle_status: 'VALID', session_status: 'COMPLETED', protection_state: 'COMPLETED_VERIFIED',
    incidents: [{ enforcement_action: 'CONTAIN' }, { enforcement_action: 'REFUSE' }] }
  const verdict = deriveVerdict(blocked)
  assert.equal(verdict.tone, 'ok')
  assert.ok(verdict.headline.includes('막았'))
})
test('blocked policy incidents exclude separate unevaluated observations from the success count', () => {
  const result = {
    bundle_status: 'VALID',
    session_status: 'COMPLETED',
    protection_state: 'COMPLETED_VERIFIED',
    incident_count: 1,
    incidents: [{ enforcement_action: 'BLOCKED', execution_result: 'SUCCEEDED' }],
    unevaluated_observations: { count: 3, items: [
      { process_name: 'helper-a.exe', process_role: 'DESCENDANT', reason_code: 'VERIFIED_AGENT_PROCESS' },
      { process_name: 'helper-b.exe', process_role: 'DESCENDANT', reason_code: 'VERIFIED_AGENT_PROCESS' },
      { process_name: 'helper-c.exe', process_role: 'DESCENDANT', reason_code: 'VERIFIED_AGENT_PROCESS' },
    ] },
  }
  const verdict = deriveVerdict(result)
  assert.equal(verdict.branch, 'SUCCESS')
  assert.equal(verdict.tone, 'ok')
  assert.ok(verdict.headline.includes('위협 1건'))
  assert.ok(!verdict.headline.includes('4건'))
  assert.ok(verdict.detail.includes('그 밖에 명령줄을 읽지 못한 보조 프로세스 3건은 판정하지 못했어요.'))
})

test('observations alone keep a verified run successful and explain what was not assessed', () => {
  const verdict = deriveVerdict({
    bundle_status: 'VALID',
    session_status: 'COMPLETED',
    protection_state: 'COMPLETED_VERIFIED',
    incident_count: 0,
    incidents: [],
    unevaluated_observations: { count: 2, items: [
      { process_name: 'helper.exe', process_role: 'DESCENDANT', reason_code: 'VERIFIED_AGENT_PROCESS' },
      { process_name: 'shell.exe', process_role: 'DESCENDANT', reason_code: 'VERIFIED_AGENT_PROCESS' },
    ] },
  })
  assert.equal(verdict.branch, 'SUCCESS')
  assert.equal(verdict.tone, 'ok')
  assert.ok(verdict.detail.includes('그 밖에 명령줄을 읽지 못한 보조 프로세스 2건은 판정하지 못했어요.'))
})

test('an actual unblocked policy incident remains a warning beside unevaluated observations', () => {
  const verdict = deriveVerdict({
    bundle_status: 'VALID',
    session_status: 'COMPLETED',
    protection_state: 'COMPLETED_VERIFIED',
    incident_count: 1,
    incidents: [{ attribution_class: 'PROCESS', enforcement_action: 'NONE', execution_result: 'NOT_ATTEMPTED' }],
    unevaluated_observations: { count: 3, items: [
      { process_name: 'helper.exe', process_role: 'DESCENDANT', reason_code: 'VERIFIED_AGENT_PROCESS' },
      { process_name: 'conhost.exe', process_role: 'DESCENDANT', reason_code: 'VERIFIED_AGENT_PROCESS' },
      { process_name: 'hook.exe', process_role: 'DESCENDANT', reason_code: 'VERIFIED_AGENT_PROCESS' },
    ] },
  })
  assert.equal(verdict.branch, 'PROCESS_DETECTED')
  assert.equal(verdict.tone, 'warn')
  assert.ok(verdict.headline.includes('1건'))
  assert.ok(!verdict.headline.includes('4건'))
})

test('an out-of-scope tool does not turn a verified run into a warning', () => {
  // A tool AIA cannot interpret is recorded (UNSUPPORTED_TOOL_PATH) but is not
  // a protection failure, so a verified bundle still reads as protected.
  const verdict = deriveVerdict({ bundle_status: 'VALID', session_status: 'COMPLETED', protection_state: 'COMPLETED_VERIFIED', limitations: ['UNSUPPORTED_TOOL_PATH'] })
  assert.notEqual(verdict.tone, 'bad')
  assert.notEqual(verdict.tone, 'warn')
  const live = guardianStatus({ selected: true, ready: true, status: { session: { status: 'COMPLETED' } }, result: { session_status: 'COMPLETED', bundle_status: 'VALID', protection_state: 'COMPLETED_VERIFIED', limitations: ['UNSUPPORTED_TOOL_PATH'] } })
  assert.notEqual(live.state, 'review')
})
test('full access live run reads as a scope choice, not an observation failure', () => {
  const base = { selected: true, ready: true, status: {
    session: { status: 'RUNNING' }, phase: 'RUNNING',
    permission_mode: 'full_access', full_access_used: true,
    protection: { state: 'DEGRADED', hook_broker: 'HEALTHY' },
    sensor_health: { FILESYSTEM_WATCHER: 'HEALTHY', AGENT_HOOK: 'HEALTHY', PROCESS_RUNTIME: 'HEALTHY' } } }
  const value = guardianStatus(base)
  assert.equal(value.state, 'normal')
  assert.ok(!value.headline.includes('확인할 수 없'))
  assert.ok(value.label.includes('전체 권한'))
  // A real observation failure still surfaces even under full access.
  const brokerDown = guardianStatus({ ...base, status: { ...base.status, protection: { state: 'DEGRADED', hook_broker: 'FAILED' } } })
  assert.equal(brokerDown.state, 'review')
  const sensorDown = guardianStatus({ ...base, status: { ...base.status, sensor_health: { AGENT_HOOK: 'FAILED' } } })
  assert.equal(sensorDown.state, 'review')
})
test('a hidden child process caught after it ran is detection, not a block', () => {
  // Process-tree attribution with no real enforcement action: AIA observed it
  // after the fact (the Hook never gated the child), so it is not "막았어요".
  const r = { bundle_status: 'VALID', session_status: 'COMPLETED', protection_state: 'COMPLETED_VERIFIED',
    incidents: [{ attribution_class: 'PROCESS', policy_effect: 'DENY', enforcement_action: '', execution_result: 'NOT_ATTEMPTED', summary: 'powershell Remove-Item' }] }
  const v = deriveVerdict(r)
  assert.equal(v.branch, 'PROCESS_DETECTED')
  assert.ok(v.headline.includes('프로세스 센서'))
  assert.ok(!v.headline.includes('막았'))
  assert.equal(v.tone, 'warn')
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
