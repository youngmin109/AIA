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

test('a rejected write fetches a new local capability once and retries', async () => {
  const original = globalThis.fetch
  let issued = 0
  let accepted = null
  const sent = []
  globalThis.fetch = async (path, options) => {
    if (path === '/api/local-session') {
      issued += 1
      return new Response(JSON.stringify({ token: `capability-${issued}` }), { status: 200 })
    }
    sent.push(options.headers['X-AIA-Local-Token'])
    const ok = options.headers['X-AIA-Local-Token'] === accepted
    return new Response(JSON.stringify(ok ? { ok: true } : { error: 'rejected' }), { status: ok ? 200 : 403 })
  }
  try {
    const { resetLocalSessionToken } = await import('../src/api/localSession.ts')
    resetLocalSessionToken()
    accepted = 'capability-2'  // the server restarted after the page cached capability-1
    await apiPost('/warm-up', {}).catch(() => {})
    sent.length = 0
    accepted = 'capability-3'
    assert.deepEqual(await apiPost('/after-restart', {}), { ok: true })
    assert.deepEqual(sent, ['capability-2', 'capability-3'])
    sent.length = 0
    accepted = null  // a request that stays rejected is retried only once
    await assert.rejects(apiPost('/foreign', {}), /rejected/)
    assert.equal(sent.length, 2)
  } finally { globalThis.fetch = original }
})
