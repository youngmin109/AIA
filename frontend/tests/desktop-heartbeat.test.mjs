import test from 'node:test'
import assert from 'node:assert/strict'
import { startDesktopHeartbeat } from '../src/desktopBridge.ts'

function fakeDesktop({ hidden = false, bridge = true } = {}) {
  const listeners = {}
  const timers = []
  const beats = []
  const add = (name, fn) => { listeners[name] = fn }
  globalThis.document = { hidden, addEventListener: add, removeEventListener: (name) => { delete listeners[name] } }
  globalThis.window = {
    setInterval: (fn) => { timers.push(fn); return timers.length },
    clearInterval: () => { timers.length = 0 },
    addEventListener: add,
    removeEventListener: (name) => { delete listeners[name] },
    pywebview: bridge ? { api: { heartbeat: async () => { beats.push(1); return true } } } : undefined,
  }
  return { listeners, timers, beats }
}

test('a visible page beats on the timer, on becoming visible and when the bridge is ready', () => {
  const desktop = fakeDesktop()
  const stop = startDesktopHeartbeat(10_000)
  desktop.timers[0]()
  desktop.listeners.visibilitychange()
  desktop.listeners.pywebviewready()
  assert.equal(desktop.beats.length, 3)
  stop()
  assert.equal(desktop.timers.length, 0)
  assert.equal(desktop.listeners.visibilitychange, undefined)
})

test('a hidden page or a plain browser sends nothing', () => {
  const hidden = fakeDesktop({ hidden: true })
  startDesktopHeartbeat()
  hidden.timers[0]()
  assert.equal(hidden.beats.length, 0)
  const browser = fakeDesktop({ bridge: false })
  startDesktopHeartbeat()
  assert.doesNotThrow(() => browser.timers[0]())
})
