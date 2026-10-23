import assert from 'node:assert/strict'
import test from 'node:test'
import { ackKeys, eventKey, isFlagged, latestAcked, pendingReviews } from '../src/api/evidenceReview.ts'

const flagged = id => ({ event_id: id, category: 'POLICY', severity: 'WARNING' })
const info = id => ({ event_id: id, category: 'POLICY', severity: 'INFO' })
const sensor = id => ({ event_id: id, category: 'SENSOR', severity: 'CRITICAL' })
const many = n => Array.from({ length: n }, (_, i) => flagged(`event-${String(i + 1).padStart(3, '0')}`))

test('a finished run never prompts, so reopening the app does not bury the start screen', () => {
  assert.deepEqual(pendingReviews('run-1', many(50), {}, false), [])
  assert.deepEqual(pendingReviews(null, many(5), {}, true), [])
})

test('a running run prompts for flagged events only, oldest first', () => {
  const events = [info('a'), flagged('b'), sensor('c'), flagged('d')]
  const pending = pendingReviews('run-1', events, {}, true)
  assert.deepEqual(pending.map(item => item.index), [1, 3])
  assert.equal(pending[0].key, 'run-1:b')
  assert.equal(isFlagged(sensor('c')), false)
  assert.equal(isFlagged(info('a')), false)
})

test('one mark clears the first event and acknowledging all clears the whole wall at once', () => {
  const events = many(50)
  let acked = {}
  const first = pendingReviews('run-1', events, acked, true)
  assert.equal(first.length, 50)

  acked = ackKeys(acked, [first[0].key], 'reviewed')
  assert.equal(pendingReviews('run-1', events, acked, true).length, 49)

  acked = ackKeys(acked, pendingReviews('run-1', events, acked, true).map(item => item.key), 'reviewed')
  assert.deepEqual(pendingReviews('run-1', events, acked, true), [])
})

test('events that arrive after "acknowledge all" prompt again', () => {
  const events = many(10)
  let acked = ackKeys({}, pendingReviews('run-1', events, {}, true).map(item => item.key), 'reviewed')
  const later = [...events, flagged('event-late')]
  const pending = pendingReviews('run-1', later, acked, true)
  assert.deepEqual(pending.map(item => item.key), ['run-1:event-late'])
})

test('marks of other runs do not hide this run and the stored map stays small', () => {
  const acked = ackKeys({}, ['other-run:event-001'], 'reviewed')
  assert.equal(pendingReviews('run-1', many(3), acked, true).length, 3)

  const huge = ackKeys({}, Array.from({ length: 900 }, (_, i) => `run-${'x'.repeat(36)}:${'e'.repeat(36)}-${i}`), 'problem')
  assert.ok(Object.keys(huge).length <= 500)
  assert.ok(new TextEncoder().encode(JSON.stringify(huge)).byteLength <= 8 * 1024)
  assert.ok(Object.keys(huge).at(-1).endsWith('-899'))
  assert.deepEqual(latestAcked({}), {})
})

test('events without ids still get a stable key', () => {
  assert.equal(eventKey('run-1', {}, 4), 'run-1:idx4')
  assert.equal(eventKey('run-1', { chain_action_id: 'act' }, 4), 'run-1:act')
})
