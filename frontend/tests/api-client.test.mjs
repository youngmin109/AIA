import test from 'node:test'
import assert from 'node:assert/strict'
import { apiPost, apiPostTolerant } from '../src/api/client.ts'

test('normal and tolerant writes both carry local browser capability', async () => {
  const original = globalThis.fetch
  const calls = []
  globalThis.fetch = async (path, options) => {
    calls.push({ path, options })
    return path === '/api/local-session'
      ? new Response(JSON.stringify({ token: 'test-local-capability' }), {status: 200})
      : new Response(JSON.stringify({ reason: 'HOOK_VERIFICATION_REQUIRED' }), {status: path === '/normal' ? 200 : 409})
  }
  try {
    await apiPost('/normal', {})
    const result = await apiPostTolerant('/api/hook/verify')
    assert.equal(result.reason, 'HOOK_VERIFICATION_REQUIRED')
    assert.equal(calls.filter(call => call.path === '/api/local-session').length, 1)
    for (const call of calls.filter(call => call.path !== '/api/local-session')) {
      assert.equal(call.options.headers['X-AIA-Local-Token'], 'test-local-capability')
    }
  } finally { globalThis.fetch = original }
})
