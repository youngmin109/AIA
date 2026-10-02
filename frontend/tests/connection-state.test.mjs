import test from 'node:test'
import assert from 'node:assert/strict'
import { CONNECTION_LOST_AFTER, isConnectionLost, nextConnectionFailures, pollOutcomeOf } from '../src/api/connectionState.ts'
import { errorReportTemplate } from '../src/api/errorReport.ts'

test('only polls without any response count toward a lost connection', () => {
  let failures = 0
  failures = nextConnectionFailures(failures, 'network-error')
  assert.equal(isConnectionLost(failures), false)
  failures = nextConnectionFailures(failures, 'network-error')
  assert.equal(failures, CONNECTION_LOST_AFTER)
  assert.equal(isConnectionLost(failures), true)
  assert.equal(nextConnectionFailures(failures, 'http-error'), 0)
  assert.equal(nextConnectionFailures(failures, 'ok'), 0)
})

test('fetch network failures and HTTP errors are told apart', () => {
  assert.equal(pollOutcomeOf(new TypeError('Failed to fetch')), 'network-error')
  assert.equal(pollOutcomeOf(new Error('요청 실패 (500)')), 'http-error')
})

test('the error report carries the screen error but keeps the privacy reminder', () => {
  const report = errorReportTemplate('TypeError: x is undefined')
  assert.ok(report.includes('TypeError: x is undefined'))
  assert.ok(report.includes('민감한 정보는 삭제'))
  assert.ok(!errorReportTemplate().includes('화면 오류 내용'))
})
