/** Record folder size and the snapshot clean-up, in display form. */
export interface StorageSummary {
  path: string
  total_bytes: number
  snapshot_bytes: number
  keep_recent_runs: number
  prunable_runs: number
  prunable_bytes: number
}

export interface StoragePruneResult {
  pruned_runs: number
  freed_bytes: number
  keep_recent_runs: number
}

/** 1,536 → "1.5KB", 607,000,000 → "579MB": one decimal below 10, none above. */
export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return '—'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let value = bytes
  let unit = 0
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024
    unit += 1
  }
  const shown = unit === 0 || value >= 10 ? Math.round(value).toString() : value.toFixed(1).replace(/\.0$/, '')
  return `${shown}${units[unit]}`
}

export function pruneResultNotice(result: StoragePruneResult): string {
  return result.pruned_runs > 0
    ? `오래된 실행 ${result.pruned_runs}개의 기준점 사본을 지워 ${formatBytes(result.freed_bytes)}를 비웠어요. 감사 기록은 그대로예요.`
    : '지울 기준점 사본이 없어요.'
}
