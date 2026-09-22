import type { EvidenceSummary } from '../../api/types'

// Sensor keys/labels and the count formula are ported verbatim from
// workbench.html's sensor cards (label map ~line 793, counts ~1966-1973)
// for continuity with what users already recognize from the old product.
const SENSORS: Array<{ key: string; label: string; count: (summary: EvidenceSummary) => number }> = [
  { key: 'AGENT_HOOK', label: 'Hook Sensor', count: (s) => (s.pretool_events ?? 0) + (s.posttool_events ?? 0) },
  { key: 'FILESYSTEM_WATCHER', label: 'File Sensor', count: (s) => s.filesystem_events ?? 0 },
  { key: 'PROCESS_RUNTIME', label: 'Process Sensor', count: (s) => s.process_observed ?? 0 },
]

function healthTone(health: string | undefined): 'ok' | 'warn' | 'bad' {
  const upper = String(health || '').toUpperCase()
  if (upper === 'HEALTHY') return 'ok'
  if (!upper) return 'warn'
  return 'bad'
}

export function SensorHealthRow({
  sensorHealth,
  evidenceSummary,
}: {
  sensorHealth?: Record<string, string>
  evidenceSummary?: EvidenceSummary
}) {
  if (!sensorHealth && !evidenceSummary) return null

  return (
    <div className="panel-section">
      <p className="panel-section-title">센서 상태</p>
      {SENSORS.map((sensor) => {
        const health = sensorHealth?.[sensor.key]
        const count = evidenceSummary ? sensor.count(evidenceSummary) : undefined
        return (
          <div key={sensor.key} className="stat-card">
            <div className="stat-card-label">{sensor.label}</div>
            <div className={`stat-card-value is-${healthTone(health)}`}>{health ?? '확인 중'}</div>
            {count !== undefined && <div className="stat-card-label">관찰 {count}건</div>}
          </div>
        )
      })}
    </div>
  )
}
