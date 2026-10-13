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
