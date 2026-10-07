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
