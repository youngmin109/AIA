import assert from 'node:assert/strict'
import test from 'node:test'

const { startupFailureView } = await import('../src/api/startupFailure.ts')

const workspace = 'C:\\workspace\\01_projects\\aia\\AIA-loop'

test('an unreadable folder names the item inside the work folder and how to fix it', () => {
  const view = startupFailureView(
    'CheckpointCreationError: Workspace directory cannot be read: C:\\workspace\\01_projects\\aia\\AIA-loop\\tmp\\pf08-after-8syit7pa',
    workspace,
  )

  assert.equal(view.title, '보호를 시작하지 못했어요')
  assert.equal(view.item, 'tmp\\pf08-after-8syit7pa')
  assert.match(view.hint, /작업 폴더 밖으로 옮기거나/)
  assert.match(view.detail, /^CheckpointCreationError/)
})

test('an unreadable file and an uninspectable entry read the same way', () => {
  assert.equal(
    startupFailureView('CheckpointCreationError: Workspace file cannot be read: c:/WORKSPACE/01_projects/aia/AIA-loop/data/a.db', workspace).item,
    'data/a.db',
  )
  assert.equal(
    startupFailureView('CheckpointCreationError: Workspace entry cannot be inspected: D:\\other\\x', workspace).item,
    'D:\\other\\x',
  )
})

test('a work folder that holds the AIA record folder explains the evidence boundary', () => {
  const view = startupFailureView('ControlRootValidationError: control_root and workspace must not overlap', 'C:\\')

  assert.equal(view.title, '이 폴더는 작업 폴더로 고를 수 없어요')
  assert.match(view.reason, /증거/)
  assert.match(view.hint, /프로젝트 폴더/)
})

test('a folder that changed during the checkpoint asks to retry', () => {
  const view = startupFailureView('WorkspaceChangedDuringCheckpoint: Workspace file changed during copy: a.txt', workspace)

  assert.equal(view.title, '보호를 시작하지 못했어요')
  assert.match(view.reason, /바뀌었어요/)
})

test('an unknown failure keeps the raw reason instead of claiming success', () => {
  assert.deepEqual(startupFailureView('RuntimeError: broker lost', workspace), {
    title: '보호 실행이 실패로 끝났어요',
    reason: '아래 오류 원문에 이유가 있어요.',
    item: null,
    hint: null,
    detail: 'RuntimeError: broker lost',
  })
  assert.equal(startupFailureView(null, workspace).detail, null)
})

test('a run that failed before any result is labelled and routed as a failed start', async () => {
  const { failedBeforeResult, sessionStateLabel } = await import('../src/api/sessionNavigation.ts')
  const failedStart = { session_id: 'r', status: 'FAILED', bundle_status: 'UNVERIFIED', hook_event_count: 0 }

  assert.equal(failedBeforeResult(failedStart), true)
  assert.equal(sessionStateLabel(failedStart), '시작 실패')
  assert.equal(failedBeforeResult({ ...failedStart, bundle_status: 'VALID' }), false)
  assert.equal(failedBeforeResult({ ...failedStart, hook_event_count: 3 }), false)
  assert.equal(sessionStateLabel({ ...failedStart, hook_event_count: 3 }), '실행 실패')
})
