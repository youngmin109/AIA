import assert from 'node:assert/strict'
import test from 'node:test'
import { flushUiPreferenceWrites, queueUiPreferenceWrite, restoreUiPreferences } from '../src/api/preferenceSync.ts'

if (!globalThis.CustomEvent) {
  globalThis.CustomEvent = class CustomEvent extends Event {
    constructor(type, options = {}) { super(type); this.detail = options.detail }
  }
}

function freshLaunch() {
  const store = new Map()
  globalThis.localStorage = {
    getItem: key => store.has(key) ? store.get(key) : null,
    setItem: (key, value) => { store.set(key, String(value)) },
  }
  globalThis.window = new EventTarget()
  globalThis.window.localStorage = globalThis.localStorage
}

function json(value, status = 200) {
  return new Response(JSON.stringify(value), { status })
}

test('server preferences fill missing local keys and invoke their apply callback', async () => {
  freshLaunch()
  const original = globalThis.fetch
  globalThis.fetch = async path => path === '/api/ui-preferences'
    ? json({ 'aia.tint': 'teal', 'aia.unknown': 'ignored' })
    : json({})
  const applied = []
  try {
    await restoreUiPreferences(key => applied.push(key))
    assert.equal(localStorage.getItem('aia.tint'), 'teal')
    assert.equal(localStorage.getItem('aia.unknown'), null)
    assert.deepEqual(applied, ['aia.tint'])
  } finally {
    await flushUiPreferenceWrites()
    globalThis.fetch = original
  }
})

test('existing local values stay unchanged and are sent to the server', async () => {
  freshLaunch()
  localStorage.setItem('aia.glass', 'on')
  const original = globalThis.fetch
  const writes = []
  globalThis.fetch = async (path, options) => {
    if (path === '/api/local-session') return json({ token: 'test-token' })
    if (path === '/api/ui-preferences' && options?.method === 'POST') writes.push(JSON.parse(options.body))
    if (path === '/api/ui-preferences') return json({ 'aia.glass': 'off' })
    return json({ saved: true })
  }
  try {
    await restoreUiPreferences(() => assert.fail('existing local key must not be reapplied'))
    await flushUiPreferenceWrites()
    assert.equal(localStorage.getItem('aia.glass'), 'on')
    assert.deepEqual(writes, [{ key: 'aia.glass', value: 'on' }])
  } finally { globalThis.fetch = original }
})

test('server failure is silent and leaves startup usable', async () => {
  freshLaunch()
  const original = globalThis.fetch
  globalThis.fetch = async () => { throw new TypeError('offline') }
  try {
    await assert.doesNotReject(restoreUiPreferences(() => assert.fail('nothing should be applied')))
    queueUiPreferenceWrite('aia.tint', 'teal')
    await assert.doesNotReject(flushUiPreferenceWrites())
  } finally { globalThis.fetch = original }
})

test('unknown keys and non-string server values are ignored', async () => {
  freshLaunch()
  const original = globalThis.fetch
  globalThis.fetch = async () => json({ 'aia.unknown': 'ignored', 'aia.tint': 12 })
  const applied = []
  try {
    await restoreUiPreferences(key => applied.push(key))
    assert.equal(localStorage.getItem('aia.unknown'), null)
    assert.equal(localStorage.getItem('aia.tint'), null)
    assert.deepEqual(applied, [])
  } finally { globalThis.fetch = original }
})
