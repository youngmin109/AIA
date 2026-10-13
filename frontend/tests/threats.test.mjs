import test from 'node:test'
import assert from 'node:assert/strict'
import { massChange, threatCounts, threatOf, threatsOf } from '../src/api/threats.ts'

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
