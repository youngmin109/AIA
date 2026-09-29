import type { EvidenceSummary } from '../../api/types'

// Sensor keys and the count formula are ported from workbench.html's sensor
// cards (counts ~1966-1973). The labels drop the word "Sensor" because the
// tiles sit side by side under a "센서 상태" heading.
const SENSORS: Array<{ key: string; label: string; count: (summary: EvidenceSummary) => number }> = [
  { key: 'AGENT_HOOK', label: 'Hook', count: (s) => (s.pretool_events ?? 0) + (s.posttool_events ?? 0) },
  { key: 'FILESYSTEM_WATCHER', label: 'File', count: (s) => s.filesystem_events ?? 0 },
  { key: 'PROCESS_RUNTIME', label: 'Process', count: (s) => s.process_observed ?? 0 },
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
      <div className="sensor-health-grid">
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
    </div>
  )
}
