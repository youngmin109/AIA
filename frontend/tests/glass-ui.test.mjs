import test from 'node:test'
import assert from 'node:assert/strict'
import { barPercent, bucketCounts, donutArcs, remainingSeconds, verdictSlices } from '../src/api/chartMath.ts'
import { normalizeTintPreference } from '../src/api/tintPreference.ts'

test('donut arcs split the circle by value and skip empty slices', () => {
  const arcs = donutArcs([
    { key: 'a', label: 'a', value: 3, tone: 'allow' },
    { key: 'b', label: 'b', value: 0, tone: 'log' },
    { key: 'c', label: 'c', value: 1, tone: 'block' },
  ])
  assert.deepEqual(arcs.map(arc => [arc.key, arc.length, arc.offset]), [['a', 75, -0], ['c', 25, -75]])
  assert.deepEqual(donutArcs([{ key: 'x', label: 'x', value: 0, tone: 'allow' }]), [])
})

test('verdict slices separate allowed from audited and keep block as a decision', () => {
  const slices = verdictSlices({ compliant: 48, audit: 6, violation: 1, indeterminate: 0 })
  assert.deepEqual(slices.map(slice => [slice.key, slice.value]), [['allow', 42], ['log', 6], ['block', 1], ['unknown', 0]])
  assert.equal(slices.find(slice => slice.key === 'block').label, '차단 판정')
  assert.ok(verdictSlices(null).every(slice => slice.value === 0))
})

test('bars keep small values visible and never exceed the track', () => {
  assert.equal(barPercent(0, 10), 0)
  assert.equal(barPercent(1, 1000), 3)
  assert.equal(barPercent(20, 10), 100)
  assert.equal(barPercent(5, 0), 0)
})

test('activity buckets count recent timestamps oldest first', () => {
  const now = Date.parse('2026-10-06T12:05:00Z')
  const counts = bucketCounts(['2026-10-06T12:04:30Z', '2026-10-06T12:04:59Z', '2026-10-06T12:00:10Z', '2026-10-06T11:00:00Z', 'bad'], now)
  assert.deepEqual(counts, [1, 0, 0, 0, 2])
})

test('approval countdown exists only with a deadline', () => {
  const now = Date.parse('2026-10-06T12:00:00Z')
  assert.equal(remainingSeconds(null, now), null)
  assert.equal(remainingSeconds('2026-10-06T12:00:18.2Z', now), 19)
  assert.equal(remainingSeconds('2026-10-06T11:59:00Z', now), 0)
})

test('color theme falls back to violet', () => {
  assert.equal(normalizeTintPreference(null), 'violet')
  assert.equal(normalizeTintPreference('teal'), 'teal')
  assert.equal(normalizeTintPreference('light'), 'violet')
})

test('home pillars only call pre-execution blocking ready when every Hook check passes', async () => {
  const { blockingPillar, recoveryPillar, formatElapsed } = await import('../src/api/homeStatus.ts')
  const ok = name => ({ name, label: name, ok: true })
  assert.equal(blockingPillar(null), 'checking')
  assert.equal(blockingPillar([ok('pretool_hook'), ok('codex_hook_trust'), ok('hook_verification')]), 'ready')
  assert.equal(blockingPillar([ok('pretool_hook'), { ...ok('hook_verification'), ok: false }]), 'setup')
  assert.equal(recoveryPillar([ok('control_root')]), 'ready')
  assert.equal(recoveryPillar([]), 'checking')
  assert.equal(formatElapsed(65_000), '1:05')
  assert.equal(formatElapsed(3_725_000), '1:02:05')
})
