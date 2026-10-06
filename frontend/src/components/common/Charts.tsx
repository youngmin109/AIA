import { barPercent, donutArcs, type DonutSlice } from '../../api/chartMath'

const RADIUS = 15.9155 // circumference 100, so arc lengths are percentages

/** Ring chart drawn with SVG attributes (no inline styles). */
export function DonutChart({ slices, centerValue, centerLabel, label }: {
  slices: DonutSlice[]
  centerValue: string | number
  centerLabel: string
  label: string
}) {
  const arcs = donutArcs(slices)
  return (
    <div className="chart-donut" role="img" aria-label={label}>
      <svg viewBox="0 0 42 42" aria-hidden="true">
        <circle className="track" cx="21" cy="21" r={RADIUS} fill="none" strokeWidth="5" />
        {arcs.map(arc => (
          <circle
            key={arc.key}
            className={`seg-${arc.tone}`}
            cx="21"
            cy="21"
            r={RADIUS}
            fill="none"
            strokeWidth="5"
            strokeDasharray={`${arc.length} ${100 - arc.length}`}
            strokeDashoffset={arc.offset}
          />
        ))}
      </svg>
      <div className="chart-donut-center" aria-hidden="true">
        <strong>{centerValue}</strong>
        <span>{centerLabel}</span>
      </div>
    </div>
  )
}

export function ChartLegend({ slices }: { slices: DonutSlice[] }) {
  return (
    <ul className="chart-legend">
      {slices.map(slice => (
        <li key={slice.key}><span className={`legend-dot is-${slice.tone}`} aria-hidden="true" />{slice.label} {slice.value}</li>
      ))}
    </ul>
  )
}

export interface BarRow { key: string; label: string; value: number; tone?: 'success' | 'warning' | 'danger' | 'accent' }

/** Horizontal bars; the max is the largest row unless given. */
export function BarList({ rows, max }: { rows: BarRow[]; max?: number }) {
  const top = max ?? Math.max(0, ...rows.map(row => row.value))
  return (
    <ul className="bar-list">
      {rows.map(row => (
        <li key={row.key} className={row.tone ? `is-${row.tone}` : undefined}>
          <span className="bar-label">{row.label}</span>
          <svg viewBox="0 0 100 10" preserveAspectRatio="none" aria-hidden="true">
            <rect className="bar-track" width="100" height="10" rx="5" />
            <rect className="bar-fill" width={barPercent(row.value, top)} height="10" rx="5" />
          </svg>
          <span className="bar-value">{row.value}</span>
        </li>
      ))}
    </ul>
  )
}

/** Small vertical bars for recent activity, oldest first. */
export function MiniBars({ values, label, hotIndexes = [] }: { values: number[]; label: string; hotIndexes?: number[] }) {
  const top = Math.max(1, ...values)
  const width = values.length * 10
  return (
    <svg className="mini-bars" viewBox={`0 0 ${width} 40`} preserveAspectRatio="none" role="img" aria-label={label}>
      {values.map((value, index) => {
        const height = value > 0 ? Math.max(4, (value / top) * 38) : 2
        const tone = hotIndexes.includes(index) ? ' is-hot' : index === values.length - 1 ? ' is-now' : ''
        return <rect key={index} className={`bar${tone}`} x={index * 10 + 2} y={40 - height} width="6" height={height} rx="2" />
      })}
    </svg>
  )
}

/** Countdown ring; shows a wait mark when there is no deadline. */
export function RingTimer({ remaining, total, label }: { remaining: number | null; total: number; label: string }) {
  const percent = remaining === null || total <= 0 ? 100 : Math.max(0, Math.min(100, (remaining / total) * 100))
  return (
    <div className="ring-timer" role="img" aria-label={label}>
      <svg viewBox="0 0 42 42" aria-hidden="true">
        <circle className="track" cx="21" cy="21" r={RADIUS} fill="none" strokeWidth="4" />
        <circle className="value" cx="21" cy="21" r={RADIUS} fill="none" strokeWidth="4" strokeDasharray={`${percent} ${100 - percent}`} />
      </svg>
      <div className="ring-timer-center" aria-hidden="true">{remaining === null ? '…' : remaining}</div>
    </div>
  )
}
