import test from 'node:test'
import assert from 'node:assert/strict'
import { sidebarSessions, isHookVerificationRun, isRunActive, sessionDestination, sessionStateLabel } from '../src/api/sessionNavigation.ts'

test('hook verification runs stay out of the sidebar only', () => {
  const check = { session_id: 'check', status: 'COMPLETED', workspace: 'C:\\Users\\me\\AppData\\Local\\Temp\\aia-hook-verify-abc123' }
  const work = { session_id: 'work', status: 'COMPLETED', workspace: 'C:\\work\\aia-hook-verify-notes\\app' }
  assert.equal(isHookVerificationRun(check), true)
  assert.equal(isHookVerificationRun(work), false)
  assert.deepEqual(sidebarSessions([check, work], null).map(run => run.session_id), ['work'])
})

test('READY and PREPARING sessions remain visible and open the workbench', () => {
  for (const status of ['READY', 'PREPARING', 'RUNNING', 'STARTING']) {
    const run = { session_id: 'r', status }
    assert.equal(isRunActive(run), true)
    assert.equal(sessionDestination(run), 'work')
  }
  assert.equal(sessionStateLabel({ session_id: 'r', status: 'READY' }), '입력 준비 완료')
})
test('completed and stopped sessions stay in sidebar history and open evidence', () => {
  const runs = ['COMPLETED', 'ABORTED', 'FAILED'].map((status, i) => ({ session_id: String(i), status, workspace: 'same-folder' }))
  assert.equal(sidebarSessions(runs, null).length, 3)
  for (const run of runs) {
    assert.equal(isRunActive(run), false)
    assert.equal(sessionDestination(run), 'history')
  }
})
test('orphaned sessions are history, not a reattachable running session', () => {
  const run = { session_id: 'r', status: 'RUNNING', runtime_reconciliation: { orphaned: true } }
  assert.equal(isRunActive(run), false)
  assert.equal(sessionDestination(run), 'history')
  assert.equal(sessionStateLabel(run), '연결 끊김 · 기록 확인')
})
test('active sessions precede recent history while a selected older session stays visible', () => {
  const runs = [
    { session_id: 'older', status: 'COMPLETED', created_at: '2026-01-01' },
    { session_id: 'recent', status: 'COMPLETED', created_at: '2026-10-01' },
    { session_id: 'live', status: 'READY', created_at: '2026-02-01' },
  ]
  assert.deepEqual(sidebarSessions(runs, null, 2).map(run => run.session_id), ['live', 'recent'])
  assert.deepEqual(sidebarSessions(runs, 'older', 2).map(run => run.session_id), ['live', 'older'])
  assert.equal(sidebarSessions([...runs, runs[0]], null).length, 3)
})
