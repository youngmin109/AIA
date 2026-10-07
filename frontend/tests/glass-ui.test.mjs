import test from 'node:test'
import assert from 'node:assert/strict'
import { barPercent, bucketCounts, donutArcs, remainingSeconds, verdictSlices } from '../src/api/chartMath.ts'
import { normalizeTintPreference } from '../src/api/tintPreference.ts'
import { readFileSync } from 'node:fs'

test('mounted recovery views refresh when another view completes a restore', () => {
  const source = readFileSync(new URL('../src/hooks/useRecoveryStatus.ts', import.meta.url), 'utf8')
  assert.ok(source.includes("window.addEventListener('aia:result-updated', updated)"))
  assert.ok(source.includes("window.removeEventListener('aia:result-updated', updated)"))
  assert.ok(source.includes('detail === sessionId'))
})

test('donut arcs split the circle by value and skip empty slices', () => {
  const arcs = donutArcs([
    { key: 'a', label: 'a', value: 3, tone: 'allow' },
    { key: 'b', label: 'b', value: 0, tone: 'log' },
    { key: 'c', label: 'c', value: 1, tone: 'block' },
  ])
  assert.deepEqual(arcs.map(arc => [arc.key, arc.length, arc.offset]), [['a', 75, -0], ['c', 25, -75]])
  assert.deepEqual(donutArcs([{ key: 'x', label: 'x', value: 0, tone: 'allow' }]), [])
})

test('verdict slices do not equate policy violations with containment decisions', () => {
  const slices = verdictSlices({ compliant: 48, audit: 6, violation: 1, indeterminate: 0 })
  assert.deepEqual(slices.map(slice => [slice.key, slice.value]), [['allow', 42], ['log', 6], ['block', 1], ['unknown', 0]])
  assert.equal(slices.find(slice => slice.key === 'block').label, '정책 위반')
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
  assert.equal(blockingPillar([ok('pretool_hook')]), 'checking')
  assert.equal(blockingPillar([ok('pretool_hook'), ok('codex_hook_trust')]), 'checking')
  assert.equal(blockingPillar([ok('pretool_hook'), ok('codex_hook_trust'), ok('hook_verification')]), 'ready')
  assert.equal(blockingPillar([ok('pretool_hook'), { ...ok('hook_verification'), ok: false }]), 'setup')
  assert.equal(recoveryPillar([ok('control_root')]), 'ready')
  assert.equal(recoveryPillar([]), 'checking')
  assert.equal(formatElapsed(65_000), '1:05')
  assert.equal(formatElapsed(3_725_000), '1:02:05')
})

test('result headline keeps decision, confirmed block, and restore apart', async () => {
  const { resultHeadline, restoreSteps, fileBreakdown } = await import('../src/api/resultSummary.ts')
  assert.deepEqual(resultHeadline({ action_summary: { contain: 1, blocked: 1 }, codex_block_confirmation: 'BLOCK_CONFIRMED' }, 3), ['위험 요청 1건을 막았어요', '파일 3개가 바뀌었어요'])
  assert.deepEqual(resultHeadline({ action_summary: { contain: 2, blocked: 0 }, codex_block_confirmation: 'NOT_CONFIRMED' }, null), ['위험 요청 2건을 차단 판정했어요'])
  assert.equal(resultHeadline({ action_summary: { contain: 1, blocked: 1 }, codex_block_confirmation: 'NOT_CONFIRMED' }, null)[0], '위험 요청 1건을 차단 판정했어요')
  assert.equal(resultHeadline({ action_summary: {}, recovery_status: 'RESTORED', integrity_status: 'VERIFIED' }, 4)[1], '작업 폴더를 되돌리고 검증했어요')
  assert.equal(resultHeadline({ action_summary: {}, recovery_status: 'RESTORED', integrity_status: 'FAILED' }, 4)[1], '파일 4개가 바뀌었어요')
  assert.equal(resultHeadline({ action_summary: { terminated: 1 } }, null)[0], '프로세스 종료 1건을 확인했어요')
  assert.deepEqual(fileBreakdown([{ event_type: 'created' }, { event_type: 'deleted' }, { event_type: 'created' }, { event_type: 'odd' }]), { created: 2, modified: 0, deleted: 1, moved: 0 })
  const steps = restoreSteps({ recovery_status: 'RESTORED', planned_operation_count: 3, succeeded_operation_count: 3, failed_operation_count: 0 }, { integrity_status: 'FAILED', changed_paths: ['a'] }, '14:20')
  assert.deepEqual(steps.map(step => step.state), ['done', 'done', 'fail'])
  assert.ok(steps[2].detail.includes('불일치 1개'))
})

test('history groups runs without treating live or orphaned runs as healthy', async () => {
  const { historyState, filterRuns } = await import('../src/api/historyFilter.ts')
  const runs = [
    { session_id: 'live', status: 'RUNNING' },
    { session_id: 'ok', status: 'COMPLETED', bundle_status: 'VALID', incident_count: 0 },
    { session_id: 'incident', status: 'COMPLETED', bundle_status: 'VALID', incident_count: 2 },
    { session_id: 'unverified', status: 'COMPLETED', bundle_status: 'INVALID' },
    { session_id: 'orphan', status: 'RUNNING', runtime_reconciliation: { orphaned: true } },
  ]
  assert.deepEqual(runs.map(historyState), ['live', 'ok', 'review', 'review', 'orphaned'])
  assert.deepEqual(filterRuns(runs, 'ok').map(run => run.session_id), ['ok'])
  assert.deepEqual(filterRuns(runs, 'review').map(run => run.session_id), ['incident', 'unverified', 'orphan'])
  assert.equal(filterRuns(runs, 'all').length, 5)
})

test('settings lights never call an unverified connection healthy', async () => {
  const { connectionLights } = await import('../src/api/settingsStatus.ts')
  const { normalizeGlassPreference } = await import('../src/api/glassPreference.ts')
  assert.deepEqual(connectionLights(null).map(light => light.state), ['checking', 'checking', 'checking'])
  const ready = connectionLights({ checks: [{ name: 'pretool_hook', ok: true }, { name: 'codex_hook_trust', ok: true }, { name: 'hook_verification', ok: true }] })
  assert.deepEqual(ready.map(light => light.state), ['ok', 'ok', 'ok'])
  const stale = connectionLights({ checks: [{ name: 'pretool_hook', ok: true }], hook_trust: { status: 'TRUSTED' }, hook_activation: { status: 'OBSERVED_IN_PAST' } })
  assert.deepEqual(stale.map(light => light.state), ['ok', 'ok', 'warn'])
  const missing = connectionLights({ checks: [{ name: 'pretool_hook', ok: false }] })
  assert.deepEqual(missing.map(light => light.state), ['warn', 'warn', 'warn'])
  assert.equal(normalizeGlassPreference('off'), 'off')
  assert.equal(normalizeGlassPreference(null), 'on')
})

test('refraction maps are neutral in the centre and only push inward at the rim', async () => {
  const { displacementMap, rimMask, LENS_KINDS } = await import('../src/api/lensMap.ts')
  const map = decodeURIComponent(displacementMap(400, 200, 40).replace('data:image/svg+xml,', ''))
  assert.ok(map.startsWith('<svg'))
  assert.ok(map.includes("offset='0.0000' stop-color='rgb(255,0,0)'"), 'left edge samples inward (+x)')
  assert.ok(map.includes("offset='1.0000' stop-color='rgb(0,0,0)'"), 'right edge samples inward (-x)')
  assert.ok(map.includes("offset='0.1000' stop-color='rgb(128,0,0)'"), 'neutral at the inner bezel')
  assert.ok(decodeURIComponent(rimMask(400, 200, 30, 40)).includes("stroke-width='72.0'"))
  assert.deepEqual(Object.keys(LENS_KINDS), ['hero', 'panel', 'dialog'])
})

test('guardian pet stays inside the window and remembers where it was dropped', async () => {
  const { PET_SIZE, normalizePetPreference, normalizePetPosition, petPixels, petPosition } = await import('../src/api/petPreference.ts')
  assert.equal(normalizePetPreference(null), 'on')
  assert.equal(normalizePetPreference('off'), 'off')
  assert.deepEqual(normalizePetPosition(null), { x: 1, y: 1 })
  assert.deepEqual(normalizePetPosition({ x: -2, y: 0.5 }), { x: 0, y: 0.5 })
  assert.deepEqual(normalizePetPosition({ x: 'left', y: 3 }), { x: 1, y: 1 })
  const window = { width: 1440, height: 900 }
  assert.deepEqual(petPixels({ x: 1, y: 1 }, window), { left: 1440 - PET_SIZE - 12, top: 900 - PET_SIZE - 12 })
  assert.deepEqual(petPixels({ x: 0, y: 0 }, window), { left: 12, top: 12 })
  assert.deepEqual(petPosition({ left: 5000, top: -40 }, window), { x: 1, y: 0 })
  assert.deepEqual(petPixels(petPosition({ left: 600, top: 300 }, window), window), { left: 600, top: 300 })
  assert.deepEqual(petPixels({ x: 1, y: 1 }, { width: 60, height: 60 }), { left: 12, top: 12 })
})

test('recent activity counts only agent-side records and says when the list was cut', async () => {
  const { activityBuckets } = await import('../src/api/chartMath.ts')
  const now = Date.parse('2026-10-07T01:00:00Z')
  const at = seconds => new Date(now - seconds * 1000).toISOString()
  const timeline = [
    { record_type: 'SENSOR_HEALTH', captured_at: at(30) },
    { record_type: 'PROCESS_OBSERVED', captured_at: at(30) },
    { record_type: 'PRETOOL_REQUEST', captured_at: at(10) },
    { record_type: 'COMMAND_OBSERVED', captured_at: at(10) },
    { record_type: 'POSTTOOL_OBSERVED', captured_at: at(9) },
    { record_type: 'PROCESS_EXIT_OBSERVED', captured_at: at(5) },
    { record_type: 'FILESYSTEM_EVENT', captured_at: at(200) },
  ]
  assert.deepEqual(activityBuckets(timeline, now), { counts: [0, 1, 0, 0, 3], current: 3, partial: false })
  assert.deepEqual(activityBuckets(null, now), { counts: [0, 0, 0, 0, 0], current: 0, partial: false })
  const full = Array.from({ length: 80 }, () => ({ record_type: 'FILESYSTEM_EVENT', captured_at: at(20) }))
  assert.equal(activityBuckets(full, now).partial, true)
  assert.equal(activityBuckets([{ record_type: 'SENSOR_HEALTH', captured_at: at(900) }, ...full.slice(1)], now).partial, false)
})
