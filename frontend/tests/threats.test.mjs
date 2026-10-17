import test from 'node:test'
import assert from 'node:assert/strict'
import { changeLabel, massChange, missedViolationOf, missedViolationsOf, newProtectedChange, threatCounts, threatOf, threatsOf } from '../src/api/threats.ts'

const contain = (extra) => ({ enforcement_decision: 'CONTAIN', ...extra })

test('a block is named by the threat it stopped', () => {
  assert.equal(threatOf(contain({ matched_asset_types: ['SECRET'], matched_rule_ids: ['protected-secret-files'] })).title, '자격 증명 탈취 시도')
  assert.equal(threatOf(contain({ matched_asset_types: ['DATABASE_RELATED'] })).tactic, '데이터 파괴')
  // A file the user marked as protected wins over the asset it also matches.
  assert.equal(threatOf(contain({ matched_asset_types: ['WORKSPACE'], matched_rule_ids: ['aia-user-protected-path-1'] })).title, '보호 파일 파괴 시도')
  assert.equal(threatOf(contain({})).title, '정책 위반 시도')
})

test('only CONTAIN decisions are threats, and hashes never show as targets', () => {
  assert.equal(threatOf({ enforcement_decision: 'CONTINUE', matched_asset_types: ['SECRET'] }), null)
  assert.equal(threatOf(contain({ target: { display: '.env' } })).target, '.env')
  assert.equal(threatOf(contain({ target: { display: 'sha256:abcd' } })).target, null)
  assert.equal(threatOf(contain({ target: { display: '—' } })).target, null)
})

test('a VIOLATION without CONTAIN is shown with its reason, target and time', () => {
  const violation = missedViolationOf({
    action_id: 'action-1',
    policy_decision: 'VIOLATION',
    enforcement_decision: 'REFUSE',
    enforcement_reasons: ['SENSOR_UNHEALTHY'],
    target: { canonical_path: 'data/customer-ledger.csv', target_kind: 'FILE' },
    observed_at: '2026-10-17T12:00:00Z',
  })
  assert.deepEqual(violation, {
    id: 'action-1',
    title: '정책 위반 감지 · 막지 못함',
    reason: '감시 장치 하나가 정상이 아니었어요 (SENSOR_UNHEALTHY)',
    target: 'data/customer-ledger.csv',
    at: '2026-10-17T12:00:00Z',
  })
  assert.equal(missedViolationsOf([{
    policy_decision: 'VIOLATION',
    enforcement_decision: 'REFUSE',
  }]).length, 1)
})

test('CONTAIN, COMPLIANT and INDETERMINATE are not missed violations', () => {
  assert.equal(missedViolationOf({ policy_decision: 'VIOLATION', enforcement_decision: 'CONTAIN' }), null)
  assert.equal(missedViolationOf({ policy_decision: 'COMPLIANT', enforcement_decision: 'REFUSE' }), null)
  assert.equal(missedViolationOf({ policy_decision: 'INDETERMINATE', enforcement_decision: 'REFUSE' }), null)
})

test('every known reason code and unknown reason use the specified copy', () => {
  const expected = {
    SENSOR_UNHEALTHY: '감시 장치 하나가 정상이 아니었어요',
    ATTRIBUTION_NOT_EXACT: '이 요청이 보호 중인 Codex에서 왔다는 걸 확신하지 못했어요',
    AUDIT_MODE_NO_AUTOMATIC_ENFORCEMENT: '기록 모드라서 막지 않고 기록만 했어요',
    HOOK_TRUST_UNAVAILABLE: 'Hook 신뢰를 확인하지 못했어요',
    WORKSPACE_LEASE_INVALID: '작업 폴더 잠금을 확인하지 못했어요',
    WORKSPACE_LEASE_UNVERIFIABLE: '작업 폴더 잠금을 확인하지 못했어요',
    ROOT_PROCESS_IDENTITY_INVALID: 'AIA가 띄운 Codex가 맞는지 확인하지 못했어요',
    ROOT_REGISTRATION_MISMATCH: 'AIA가 띄운 Codex가 맞는지 확인하지 못했어요',
    PROCESS_IDENTITY_MISMATCH: 'AIA가 띄운 Codex가 맞는지 확인하지 못했어요',
    LAUNCH_PROVENANCE_INVALID: 'AIA가 띄운 Codex가 맞는지 확인하지 못했어요',
    SESSION_NOT_RUNNING: '실행이 끝나가는 중이었어요',
  }
  for (const [code, copy] of Object.entries(expected)) {
    assert.equal(missedViolationOf({ policy_decision: 'VIOLATION', enforcement_reasons: [code] }).reason, copy + ' (' + code + ')')
  }
  assert.equal(missedViolationOf({ policy_decision: 'VIOLATION', enforcement_reasons: ['FUTURE_REASON'] }).reason, '막을 조건을 확인하지 못했어요 (FUTURE_REASON)')
  assert.equal(missedViolationOf({ policy_decision: 'VIOLATION', enforcement_reasons: [] }).reason, '막을 조건을 확인하지 못했어요')
})

test('audit reason uses its title and no missed-violation copy says 차단', () => {
  const missed = missedViolationOf({
    policy_decision: 'VIOLATION',
    enforcement_reasons: ['AUDIT_MODE_NO_AUTOMATIC_ENFORCEMENT'],
  })
  assert.equal(missed.title, '정책 위반 기록 · 막지 않음')
  assert.equal([missed.title, missed.reason].some(copy => copy.includes('차단')), false)
})

test('a run summary counts threats by name', () => {
  const threats = threatsOf([
    contain({ matched_asset_types: ['SECRET'] }),
    { enforcement_decision: 'CONTINUE' },
    contain({ matched_asset_types: ['SECRET'] }),
    contain({ matched_rule_ids: ['aia-user-protected-path-1'] }),
  ])
  assert.equal(threats.length, 3)
  assert.equal(threatCounts(threats), '자격 증명 탈취 시도 2 · 보호 파일 파괴 시도 1')
})

test('a mass change is a large jump between two polls', () => {
  assert.equal(massChange(null, 300), 0)
  assert.equal(massChange(10, 20), 0)
  assert.equal(massChange(10, 312), 302)
})

test('a protected file change is announced once, when the live count grows', () => {
  const changes = [{ path: 'data/customer-ledger.csv', event_type: 'deleted' }, { path: '.env', event_type: 'modified' }]
  // The first poll is the baseline: reopening a run does not replay old changes.
  assert.equal(newProtectedChange(null, 2, changes), null)
  assert.equal(newProtectedChange(2, 2, changes), null)
  assert.deepEqual(newProtectedChange(1, 2, changes), changes[0])
  assert.equal(newProtectedChange(1, null, changes), null)
  assert.equal(changeLabel('deleted'), '삭제')
  assert.equal(changeLabel('moved'), '이동')
})
