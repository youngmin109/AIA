/** Pure math for the CSS/SVG charts. Display only; never used for decisions. */

export type SliceTone = 'allow' | 'log' | 'block' | 'unknown'
export interface DonutSlice { key: string; label: string; value: number; tone: SliceTone }
/** Arc lengths are in units of a circle whose circumference is 100. */
export interface DonutArc { key: string; tone: SliceTone; length: number; offset: number }

export function donutArcs(slices: DonutSlice[]): DonutArc[] {
  const visible = slices.filter(slice => slice.value > 0)
  const total = visible.reduce((sum, slice) => sum + slice.value, 0)
  if (total <= 0) return []
  let cursor = 0
  return visible.map(slice => {
    const length = (slice.value / total) * 100
    const arc = { key: slice.key, tone: slice.tone, length, offset: -cursor }
    cursor += length
    return arc
  })
}

export interface ActionSummaryCounts {
  total?: number
  compliant?: number
  audit?: number
  violation?: number
  indeterminate?: number
}

/**
 * COMPLIANT covers both ALLOW and AUDIT effects, so allowed = compliant - audit.
 * VIOLATION is a policy finding; the Gate can refuse containment when attribution is insufficient.
 */
export function verdictSlices(summary?: ActionSummaryCounts | null): DonutSlice[] {
  const compliant = summary?.compliant ?? 0
  const audit = summary?.audit ?? 0
  return [
    { key: 'allow', label: '허용', value: Math.max(0, compliant - audit), tone: 'allow' },
    { key: 'log', label: '기록', value: audit, tone: 'log' },
    { key: 'block', label: '정책 위반', value: summary?.violation ?? 0, tone: 'block' },
    { key: 'unknown', label: '판단 보류', value: summary?.indeterminate ?? 0, tone: 'unknown' },
  ]
}

/** Bar width in percent; a non-zero value always stays visible. */
export function barPercent(value: number, max: number): number {
  if (!(max > 0) || !(value > 0)) return 0
  return Math.max(3, Math.min(100, (value / max) * 100))
}

/** Counts per time bucket, oldest first, for the recent-activity bars. */
export function bucketCounts(timestamps: Array<string | undefined | null>, now: number, buckets = 5, bucketMs = 60_000): number[] {
  const counts = new Array<number>(buckets).fill(0)
  const start = now - buckets * bucketMs
  for (const value of timestamps) {
    const time = Date.parse(value ?? '')
    if (Number.isNaN(time) || time < start || time > now) continue
    const index = Math.min(buckets - 1, Math.floor((time - start) / bucketMs))
    counts[index] += 1
  }
  return counts
}

/** Records AIA turns into actions (aia.normalizer): execution requests, commands, new
 *  processes, file changes. Sensor status, process exits and post-tool notes are left out. */
const ACTION_RECORD_TYPES = new Set(['PRETOOL_REQUEST', 'COMMAND_OBSERVED', 'PROCESS_OBSERVED', 'FILESYSTEM_EVENT'])
/** The run status carries only the latest timeline records (aia_app.presenters.evidence_timeline_views). */
export const TIMELINE_LIMIT = 80

export interface ActivityBuckets { counts: number[]; current: number; partial: boolean }

/** Per-minute counts of agent-side records for the recent-activity bars, oldest first. */
export function activityBuckets(
  timeline: Array<{ record_type?: string; captured_at?: string }> | null | undefined, now: number, buckets = 5, bucketMs = 60_000,
): ActivityBuckets {
  const records = timeline ?? []
  const counts = bucketCounts(records.filter(record => ACTION_RECORD_TYPES.has(record.record_type ?? '')).map(record => record.captured_at), now, buckets, bucketMs)
  const times = records.map(record => Date.parse(record.captured_at ?? '')).filter(Number.isFinite)
  // A full list that still starts inside the window means older minutes were cut off.
  const partial = records.length >= TIMELINE_LIMIT && times.length > 0 && Math.min(...times) > now - buckets * bucketMs
  return { counts, current: counts.at(-1) ?? 0, partial }
}

/** Seconds left before an AIA tool review times out; null when there is no deadline. */
export function remainingSeconds(expiresAt: string | undefined | null, now: number): number | null {
  if (!expiresAt) return null
  const end = Date.parse(expiresAt)
  if (Number.isNaN(end)) return null
  return Math.max(0, Math.ceil((end - now) / 1000))
}

/** Lanes of the recent-activity strip: what kind of record, drawn as one dot each. */
export type ActivityLane = 'request' | 'process' | 'file'
const LANE_OF: Record<string, ActivityLane> = {
  PRETOOL_REQUEST: 'request',
  COMMAND_OBSERVED: 'request',
  PROCESS_OBSERVED: 'process',
  FILESYSTEM_EVENT: 'file',
}
export const ACTIVITY_WINDOW_MS = 5 * 60_000
/** Heartbeat beats across the window (15 s each). */
export const PULSE_BUCKETS = 20

export interface ActivityStripData {
  /** position: 0 = five minutes ago, 1 = now. */
  marks: Array<{ lane: ActivityLane; at: number; position: number }>
  blocks: Array<{ at: number; position: number }>
  /** Records per beat, oldest first; the heartbeat spikes where work happened. */
  pulse: number[]
  /** Records in the last minute. */
  current: number
  partial: boolean
}

/** Recent activity as dots per lane, block decisions, and the heartbeat's beats. Display only. */
export function activityStrip(
  timeline: Array<{ record_type?: string; captured_at?: string }> | null | undefined,
  actions: Array<{ enforcement_decision?: string; observed_at?: string }> | null | undefined,
  now: number, windowMs = ACTIVITY_WINDOW_MS, buckets = PULSE_BUCKETS,
): ActivityStripData {
  const start = now - windowMs
  const inWindow = (time: number) => Number.isFinite(time) && time >= start && time <= now
  const records = timeline ?? []
  const marks: ActivityStripData['marks'] = []
  const pulse = new Array<number>(buckets).fill(0)
  for (const record of records) {
    const lane = LANE_OF[record.record_type ?? '']
    const at = Date.parse(record.captured_at ?? '')
    if (!lane || !inWindow(at)) continue
    const position = (at - start) / windowMs
    marks.push({ lane, at, position })
    pulse[Math.min(buckets - 1, Math.floor(position * buckets))] += 1
  }
  const blocks = (actions ?? [])
    .filter(action => action.enforcement_decision === 'CONTAIN')
    .map(action => Date.parse(action.observed_at ?? ''))
    .filter(inWindow)
    .map(at => ({ at, position: (at - start) / windowMs }))
  const times = records.map(record => Date.parse(record.captured_at ?? '')).filter(Number.isFinite)
  // A full list that still starts inside the window means older records were cut off.
  const partial = records.length >= TIMELINE_LIMIT && times.length > 0 && Math.min(...times) > start
  return { marks, blocks, pulse, current: marks.filter(mark => mark.at > now - 60_000).length, partial }
}

/** Polyline points of the heartbeat: a small beat when quiet, a taller one where records landed. */
export function heartbeatPoints(pulse: number[], x0: number, width: number, baseline: number): string {
  const round = (value: number) => Math.round(value * 10) / 10
  const step = width / Math.max(1, pulse.length)
  const points = [`${x0},${baseline}`]
  pulse.forEach((count, index) => {
    const left = x0 + index * step
    const height = count > 0 ? Math.min(12, 4 + count * 2.5) : 2.5
    points.push(
      `${round(left + step * 0.35)},${baseline}`,
      `${round(left + step * 0.5)},${round(baseline - height)}`,
      `${round(left + step * 0.62)},${round(baseline + height * 0.55)}`,
      `${round(left + step * 0.74)},${baseline}`,
    )
  })
  points.push(`${round(x0 + width)},${baseline}`)
  return points.join(' ')
}
