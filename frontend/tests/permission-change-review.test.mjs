import test from 'node:test'
import assert from 'node:assert/strict'
import { grantSummary, widensBeyondProtection } from '../src/api/permissionGrants.ts'
import { applyEvents, EMPTY_CONVERSATION } from '../src/components/terminal/codexConversation.ts'

test('mode requests are never displayed as no extra permissions or verified grants', () => {
  const request = { scope: 'mode_change_request', mode: 'auto_review', network: null, filesystem: [] }
  assert.equal(grantSummary(request), '나 대신 승인 요청 · 실제 적용은 별도 확인 필요')
  assert.equal(widensBeyondProtection([request]), true)
  assert.equal(grantSummary({ ...request, mode: 'full_access', network: true }), '전체 권한 요청 · 실제 적용은 별도 확인 필요')
})

test('permission acknowledgement does not claim verified application', () => {
  const state = applyEvents(EMPTY_CONVERSATION, [{ sequence: 1, type: 'permission.submitted', mode: 'full_access' }])
  assert.match(state.items.at(-1).text, /접수.*별도 확인/)
})
