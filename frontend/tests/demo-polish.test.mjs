import assert from 'node:assert/strict'
import test from 'node:test'

const { insideWorkspace, absoluteInWorkspace, addProtectedPaths, MAX_PROTECTED_PATHS } = await import('../src/api/protectedPaths.ts')

const workspace = 'C:\\work\\shop'

test('only paths inside the work folder can be protected', () => {
  assert.equal(insideWorkspace(workspace, 'C:\\work\\shop\\data\\customers.db'), 'data\\customers.db')
  assert.equal(insideWorkspace(workspace, 'c:/WORK/shop/data/'), 'data')
  assert.equal(insideWorkspace(workspace, 'C:\\work\\shop'), null)
  assert.equal(insideWorkspace(workspace, 'C:\\work\\shop-other\\x'), null)
  assert.equal(insideWorkspace(workspace, 'C:\\work\\shop\\..\\secret'), null)
  assert.equal(insideWorkspace('', 'C:\\work\\shop\\a'), null)
})

test('typed entries become absolute paths in the work folder', () => {
  assert.equal(absoluteInWorkspace(workspace, 'data/customers.db'), 'C:\\work\\shop\\data\\customers.db')
  assert.equal(absoluteInWorkspace(workspace, '\\certs'), 'C:\\work\\shop\\certs')
  assert.equal(absoluteInWorkspace(workspace, 'D:\\elsewhere\\file'), 'D:\\elsewhere\\file')
})

test('adding keeps each path once, skips outside paths, and stops at the limit', () => {
  const first = addProtectedPaths([], ['C:\\work\\shop\\.env', 'c:\\work\\shop\\.ENV', 'D:\\other\\x'], workspace)
  assert.deepEqual(first, { paths: ['C:\\work\\shop\\.env'], outside: 1, overLimit: 0 })
  const many = Array.from({ length: MAX_PROTECTED_PATHS + 2 }, (_, index) => `C:\\work\\shop\\f${index}`)
  const capped = addProtectedPaths([], many, workspace)
  assert.equal(capped.paths.length, MAX_PROTECTED_PATHS)
  assert.equal(capped.overLimit, 2)
})

test('storage sizes read naturally and the clean-up notice says what was freed', async () => {
  const { formatBytes, pruneResultNotice } = await import('../src/api/storageView.ts')
  assert.equal(formatBytes(512), '512B')
  assert.equal(formatBytes(1536), '1.5KB')
  assert.equal(formatBytes(607_000_000), '579MB')
  assert.equal(formatBytes(3 * 1024 ** 3), '3GB')
  assert.equal(formatBytes(-1), '—')
  assert.match(pruneResultNotice({ pruned_runs: 2, freed_bytes: 2048, keep_recent_runs: 10 }), /2개.*2KB/)
  assert.equal(pruneResultNotice({ pruned_runs: 0, freed_bytes: 0, keep_recent_runs: 10 }), '지울 기준점 사본이 없어요.')
})

test('a command is one row: Hook check, command and Hook record fold together', async () => {
  const { groupCommands, commandPreview, hookMark } = await import('../src/components/terminal/commandRows.ts')
  const pre = { kind: 'hook', key: 'h1', eventName: 'preToolUse', status: 'completed', phase: 'completed' }
  const command = { kind: 'command', key: 'c1', command: 'dir', cwd: 'C:\\w', output: '', status: 'completed', exitCode: 0 }
  const post = { kind: 'hook', key: 'h2', eventName: 'postToolUse', status: 'completed', phase: 'completed' }
  const reply = { kind: 'agent', key: 'a1', text: 'done', streaming: false }
  const entries = groupCommands([pre, command, post, reply])
  assert.deepEqual(entries.map(entry => entry.kind), ['command', 'item'])
  assert.deepEqual(entries[0].hooks.map(hook => hook.key), ['h1', 'h2'])
  // A Hook line without a command after it (for example a blocked call) stays on its own.
  assert.deepEqual(groupCommands([pre, reply]).map(entry => entry.kind), ['item', 'item'])
  // Codex may report the command before its check; the check joins it.
  const late = groupCommands([command, pre, reply])
  assert.deepEqual(late.map(entry => entry.kind), ['command', 'item'])
  assert.deepEqual(late[0].hooks.map(hook => hook.key), ['h1'])
  // A check followed by the next command belongs to that next command.
  const second = { ...command, key: 'c2' }
  const pre2 = { ...pre, key: 'h3' }
  const twoCommands = groupCommands([pre, command, pre2, second])
  assert.deepEqual(twoCommands.map(entry => entry.hooks.map(hook => hook.key)), [['h1'], ['h3']])

  assert.equal(commandPreview('"C:\\WINDOWS\\System32\\WindowsPowerShell\\v1.0\\powershell.exe" -NoProfile -Command \'Get-ChildItem -Force | Select-Object Mode, Name\''), 'Get-ChildItem -Force | Select-Object Mode, Name')
  assert.equal(commandPreview('"C:\\Program Files\\PowerShell\\7\\pwsh.exe" -Command "Write-Output a;\n  Get-Date"'), 'Write-Output a; Get-Date')
  assert.equal(commandPreview('cmd.exe /c dir data'), 'dir data')
  assert.equal(commandPreview('git status'), 'git status')

  assert.deepEqual(hookMark([pre, post]), { text: 'Hook 확인', tone: 'hook' })
  assert.deepEqual(hookMark([{ ...pre, status: 'blocked' }]), { text: '실행 전 중단 요청', tone: 'bad' })
  assert.equal(hookMark([]), null)
})

test('external tools: plain notes, one switch at a time, and a short summary', async () => {
  const { externalToolNote, withToolAllowed, externalToolsSummary } = await import('../src/api/externalToolsView.ts')
  const nodeRepl = { name: 'node_repl', source: 'config', plugin: null, on_in_protected_runs: false, allowed: false, can_turn_off: true }
  const cua = { name: 'cua_repl', source: 'plugin', plugin: 'unified-computer-use@openai-bundled', on_in_protected_runs: true, allowed: true, can_turn_off: true }
  const other = { name: 'docs', source: 'config', plugin: null, on_in_protected_runs: false, allowed: false, can_turn_off: true }
  assert.equal(externalToolNote(nodeRepl), 'JavaScript 실행·브라우저 조작 · Codex 설정')
  assert.equal(externalToolNote(cua), '화면·마우스 조작(컴퓨터 사용) · 플러그인 unified-computer-use')
  assert.equal(externalToolNote(other), 'Codex 설정')
  assert.deepEqual(withToolAllowed(['b'], 'a', true), ['a', 'b'])
  assert.deepEqual(withToolAllowed(['a', 'b'], 'a', false), ['b'])
  assert.deepEqual(withToolAllowed(['a'], 'a', true), ['a'])
  assert.equal(externalToolsSummary(null), '확인 중')
  assert.equal(externalToolsSummary({ readable: false, tools: [] }), 'Codex 설정을 읽지 못했어요')
  assert.equal(externalToolsSummary({ readable: true, tools: [nodeRepl, other] }), '2개 모두 보호 실행에서 꺼 둠')
  assert.equal(externalToolsSummary({ readable: true, tools: [nodeRepl, cua] }), '2개 중 1개 켜 둠 · 나머지는 꺼 둠')
})

test('connectors the run turned off read as off and sort after the ones still on', async () => {
  const { connectorSummary, connectorsOnFirst } = await import('../src/api/connectorView.ts')
  const on = { name: 'context7', status: 'unknown', auth: 'notLoggedIn', tool_count: 2, tools: [], error: null, turned_off_by_aia: false }
  const off = { ...on, name: 'node_repl', auth: 'unsupported', tool_count: 0, turned_off_by_aia: true }
  assert.equal(connectorSummary(off), '보호 실행에서 꺼 둠')
  // Codex 0.16x reports no runtime status; the row leaves it out instead of saying it is unknown.
  assert.equal(connectorSummary(on), '로그인 안 됨 · 도구 2개')
  assert.deepEqual(connectorsOnFirst([off, on]).map(item => item.name), ['context7', 'node_repl'])
})

test("permission: the Codex app's three choices, words and order, with full access by default", async () => {
  const { PERMISSION_DEFAULT, PERMISSION_OPTIONS, PERMISSION_TITLE, permissionAllowed, permissionModeOf, permissionModeFromCodex } = await import('../src/api/permissionMode.ts')
  assert.equal(PERMISSION_DEFAULT, 'full_access')
  assert.equal(PERMISSION_TITLE, 'ChatGPT 액션은 어떻게 승인할까요?')
  assert.deepEqual(PERMISSION_OPTIONS.map(option => option.label), ['승인 요청', '나 대신 승인', '전체 권한'])
  assert.equal(PERMISSION_OPTIONS[2].chip, '전체 액세스')
  // Codex's own profiles decide what can be picked; unknown profiles allow all.
  const full = PERMISSION_OPTIONS[2]
  assert.equal(permissionAllowed(full, []), true)
  assert.equal(permissionAllowed(full, [{ id: ':workspace', allowed: true }, { id: ':danger-full-access', allowed: false }]), false)
  assert.equal(permissionAllowed(PERMISSION_OPTIONS[1], [{ id: ':workspace', allowed: true }]), true)
  assert.equal(permissionModeOf('yolo'), null)
  assert.equal(permissionModeFromCodex('workspaceWrite', 'auto_review'), 'auto_review')
  assert.equal(permissionModeFromCodex('workspaceWrite', 'user'), 'workspace')
  assert.equal(permissionModeFromCodex('dangerFullAccess', 'user'), 'full_access')
  assert.equal(permissionModeFromCodex('readOnly', 'user'), null)
})

test("the conversation follows the applied permission, each switch, and Codex's auto-review outcomes", async () => {
  const { applyEvents, EMPTY_CONVERSATION } = await import('../src/components/terminal/codexConversation.ts')
  const ready = applyEvents(EMPTY_CONVERSATION, [{ sequence: 1, type: 'session.ready', model: 'm', sandbox: 'workspaceWrite', approvals_reviewer: 'auto_review' }])
  assert.equal(ready.permissionMode, 'auto_review')
  assert.match(ready.items.at(-1).text, /권한 나 대신 승인/)
  const switched = applyEvents(ready, [{ sequence: 2, type: 'permission.changed', mode: 'full_access' }])
  assert.equal(switched.permissionMode, 'full_access')
  assert.match(switched.items.at(-1).text, /"전체 권한"\(으\)로 바꿨어요/)
  assert.equal(applyEvents(switched, [{ sequence: 3, type: 'permission.changed', mode: 'nope' }]).permissionMode, 'full_access')
  const reviewed = applyEvents(switched, [
    { sequence: 4, type: 'auto_review.completed', status: 'denied', risk: 'high' },
    { sequence: 5, type: 'auto_review.completed', status: 'approved', risk: null },
  ])
  assert.deepEqual(reviewed.items.slice(-2).map(item => [item.tone, item.text]), [
    ['warn', 'Codex가 대신 검토하고 거절했어요 · 위험도 높음'],
    ['info', 'Codex가 대신 검토하고 승인했어요'],
  ])
})

test('recent activity strip: one dot per record in its lane, blocks, and a heartbeat that rises with work', async () => {
  const { activityStrip, heartbeatPoints, PULSE_BUCKETS } = await import('../src/api/chartMath.ts')
  const now = Date.parse('2026-10-13T03:00:00Z')
  const at = (secondsAgo) => new Date(now - secondsAgo * 1000).toISOString()
  const timeline = [
    { record_type: 'PRETOOL_REQUEST', captured_at: at(10) },
    { record_type: 'PROCESS_OBSERVED', captured_at: at(12) },
    { record_type: 'FILESYSTEM_EVENT', captured_at: at(200) },
    { record_type: 'SENSOR_HEALTH', captured_at: at(5) },
    { record_type: 'PRETOOL_REQUEST', captured_at: at(400) },
  ]
  const strip = activityStrip(timeline, [{ enforcement_decision: 'CONTAIN', observed_at: at(10) }, { enforcement_decision: 'CONTINUE', observed_at: at(9) }], now)
  assert.deepEqual(strip.marks.map(mark => mark.lane), ['request', 'process', 'file'])
  assert.equal(strip.blocks.length, 1)
  assert.ok(strip.blocks[0].position > 0.96 && strip.blocks[0].position < 1)
  assert.equal(strip.current, 2)
  assert.equal(strip.pulse.length, PULSE_BUCKETS)
  assert.equal(strip.pulse.at(-1), 2)
  assert.equal(strip.pulse.reduce((sum, value) => sum + value, 0), 3)
  assert.equal(strip.partial, false)

  // Quiet beats stay small; a busy beat is taller but capped.
  const quiet = heartbeatPoints([0], 0, 100, 50).split(' ')
  assert.equal(quiet[0], '0,50')
  assert.equal(quiet[2], '50,47.5')
  assert.equal(quiet.at(-1), '100,50')
  assert.equal(heartbeatPoints([2], 0, 100, 50).split(' ')[2], '50,41')
  assert.equal(heartbeatPoints([40], 0, 100, 50).split(' ')[2], '50,38')
})
