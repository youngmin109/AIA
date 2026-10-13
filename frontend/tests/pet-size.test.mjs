import test from 'node:test'
import assert from 'node:assert/strict'
import { normalizePetSize, readPetSize, applyPetSize, petPixelSize } from '../src/api/petSizePreference.ts'
import { petPixels, petPosition } from '../src/api/petPreference.ts'

test('pet size migrates old choices and bounds the percentage slider', () => {
  // No or unknown choice: the smallest pet.
  assert.equal(normalizePetSize(null), 70)
  assert.equal(normalizePetSize('anything'), 70)
  assert.equal(normalizePetSize('small'), 80)
  assert.equal(normalizePetSize('medium'), 100)
  assert.equal(normalizePetSize('large'), 130)
  assert.equal(normalizePetSize('toString'), 70)
  assert.equal(normalizePetSize('125'), 125)
  assert.equal(normalizePetSize(NaN), 70)
  assert.equal(normalizePetSize(65), 70)
  assert.equal(normalizePetSize(150), 140)
  assert.equal(normalizePetSize(123), 125)
  assert.ok(petPixelSize(70) < petPixelSize(100))
  assert.ok(petPixelSize(100) < petPixelSize(140))
})
test('larger browser pet remains within the viewport after resize and drag', () => {
  const viewport = { width: 640, height: 480 }, size = petPixelSize(140)
  const point = petPixels({ x: 1, y: 1 }, viewport, size)
  assert.ok(point.left + size <= viewport.width - 12)
  assert.ok(point.top + size <= viewport.height - 12)
  assert.deepEqual(petPosition({ left: 900, top: 900 }, viewport, size), { x: 1, y: 1 })
})
test('pet size persists without requiring native desktop permission', () => {
  const old = { storage: globalThis.localStorage, document: globalThis.document, window: globalThis.window }
  const values = new Map(), events = []
  globalThis.localStorage = { getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, value) }
  globalThis.document = { documentElement: { dataset: {}, style: { setProperty: (key, value) => values.set(key, value) } } }
  globalThis.window = { dispatchEvent: event => events.push(event.type) }
  try {
    applyPetSize(130)
    assert.equal(readPetSize(), 130)
    assert.equal(document.documentElement.dataset.petSize, '130')
    assert.equal(values.get('--browser-pet-size'), '135px')
    assert.deepEqual(events, ['aia:pet-size-changed'])
    globalThis.localStorage = { getItem() { throw new Error('unavailable') } }
    assert.equal(readPetSize(), 70)
  } finally { globalThis.localStorage = old.storage; globalThis.document = old.document; globalThis.window = old.window }
})
