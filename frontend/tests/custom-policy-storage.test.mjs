import assert from 'node:assert/strict'
import test from 'node:test'

// A fresh desktop launch: an empty WebView profile.
function freshLaunch() {
  const store = new Map()
  globalThis.localStorage = {
    getItem: key => (store.has(key) ? store.get(key) : null),
    setItem: (key, value) => { store.set(key, String(value)) },
  }
  globalThis.window = { localStorage: globalThis.localStorage, dispatchEvent: () => true }
}

const saved = { path: 'C:/Users/me/.aia/policies/aia-user-1.json', document: { profile: 'CUSTOM', policy_id: 'aia-user-1', rules: [{ rule_id: 'r' }] } }
const { loadCustomPolicy, readCustomPolicy } = await import('../src/components/policy/policyStorage.ts')

test('after a restart the saved custom policy comes back from the local server', async () => {
  freshLaunch()
  const original = globalThis.fetch
  const asked = []
  globalThis.fetch = async path => { asked.push(path); return new Response(JSON.stringify(saved), { status: 200 }) }
  try {
    assert.equal(readCustomPolicy(), null)
    assert.deepEqual(await loadCustomPolicy(), saved)
    assert.deepEqual(asked, ['/api/policy/custom'])
    // Kept for the rest of this launch, so the start sheet can read it synchronously.
    assert.deepEqual(readCustomPolicy(), saved)
  } finally { globalThis.fetch = original }
})

test('a policy already saved in this launch is used without asking the server', async () => {
  freshLaunch()
  globalThis.localStorage.setItem('aia.customPolicy', JSON.stringify(saved))
  const original = globalThis.fetch
  globalThis.fetch = async () => { throw new Error('must not be called') }
  try {
    assert.deepEqual(await loadCustomPolicy(), saved)
  } finally { globalThis.fetch = original }
})

test('nothing remembered, a non-custom document or no server means no custom policy', async () => {
  const original = globalThis.fetch
  try {
    for (const answer of [
      async () => new Response(JSON.stringify({ path: null, document: null }), { status: 200 }),
      async () => new Response(JSON.stringify({ ...saved, document: { ...saved.document, profile: 'PROTECTED_DEVELOPMENT' } }), { status: 200 }),
      async () => { throw new TypeError('offline') },
    ]) {
      freshLaunch()
      globalThis.fetch = answer
      assert.equal(await loadCustomPolicy(), null)
      assert.equal(readCustomPolicy(), null)
    }
  } finally { globalThis.fetch = original }
})
