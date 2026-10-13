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
