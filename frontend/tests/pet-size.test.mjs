import test from 'node:test'
import assert from 'node:assert/strict'
import { normalizePetSize, readPetSize, applyPetSize, petPixelSize } from '../src/api/petSizePreference.ts'
import { petPixels, petPosition } from '../src/api/petPreference.ts'

test('pet size defaults to medium and accepts only known sizes', () => {
  assert.equal(normalizePetSize(null), 'medium')
  assert.equal(normalizePetSize('anything'), 'medium')
  assert.equal(normalizePetSize('small'), 'small')
  assert.equal(normalizePetSize('large'), 'large')
  assert.ok(petPixelSize('small') < petPixelSize('medium'))
  assert.ok(petPixelSize('medium') < petPixelSize('large'))
})
test('larger browser pet remains within the viewport after resize and drag', () => {
  const viewport = { width: 640, height: 480 }, size = petPixelSize('large')
  const point = petPixels({ x: 1, y: 1 }, viewport, size)
  assert.ok(point.left + size <= viewport.width - 12)
  assert.ok(point.top + size <= viewport.height - 12)
  assert.deepEqual(petPosition({ left: 900, top: 900 }, viewport, size), { x: 1, y: 1 })
})
test('pet size persists without requiring native desktop permission', () => {
  const old = { storage: globalThis.localStorage, document: globalThis.document, window: globalThis.window }
  const values = new Map(), events = []
  globalThis.localStorage = { getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, value) }
  globalThis.document = { documentElement: { dataset: {} } }
  globalThis.window = { dispatchEvent: event => events.push(event.type) }
  try {
    applyPetSize('large')
    assert.equal(readPetSize(), 'large')
    assert.equal(document.documentElement.dataset.petSize, 'large')
    assert.deepEqual(events, ['aia:pet-size-changed'])
    globalThis.localStorage = { getItem() { throw new Error('unavailable') } }
    assert.equal(readPetSize(), 'medium')
  } finally { globalThis.localStorage = old.storage; globalThis.document = old.document; globalThis.window = old.window }
})
