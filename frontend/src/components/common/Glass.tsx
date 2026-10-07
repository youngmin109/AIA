import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { Icon, type IconName } from './Icon'

export type GlossTone = 'hook' | 'process' | 'file' | 'amber' | 'danger' | 'success' | 'accent'

/** Glossy gradient icon tile. */
export function GlossyIcon({ tone, icon, size }: { tone: GlossTone; icon: IconName; size?: 'sm' | 'lg' }) {
  return (
    <span className={`glossy-icon is-${tone}${size ? ` is-${size}` : ''}`} aria-hidden="true">
      <Icon name={icon} size={size === 'lg' ? 26 : size === 'sm' ? 16 : 20} />
    </span>
  )
}

/** Rotated glossy shape peeking from a tile corner. */
export function TileCorner({ tone, icon }: { tone: GlossTone; icon: IconName }) {
  return (
    <span className={`tile-corner is-${tone}`} aria-hidden="true">
      <Icon name={icon} size={24} />
    </span>
  )
}

/** Big glowing round button for the one main action of a screen. */
export function RoundAction({ small, className, children, type = 'button', ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { small?: boolean; children: ReactNode }) {
  return (
    <button type={type} className={`round-action${small ? ' is-small' : ''}${className ? ` ${className}` : ''}`} {...props}>
      {children}
    </button>
  )
}

/** Number tile: label, a big value, an optional note. */
export function StatTile({ label, value, note, tone, word, corner }: {
  label: string
  value: ReactNode
  note?: ReactNode
  tone?: 'danger' | 'success' | 'warning'
  word?: boolean
  corner?: { tone: GlossTone; icon: IconName }
}) {
  return (
    <div className={`glass-card stat-tile${tone ? ` is-${tone}` : ''}`}>
      {corner && <TileCorner tone={corner.tone} icon={corner.icon} />}
      <span className="stat-label">{label}</span>
      <strong className={`stat-value${word ? ' is-word' : ''}`}>{value}</strong>
      {note && <span className="stat-note">{note}</span>}
    </div>
  )
}

export type DotTone = 'ok' | 'warn' | 'bad' | 'neutral'

export function StatusDot({ tone }: { tone: DotTone }) {
  return <span className={`status-dot is-${tone}`} aria-hidden="true" />
}
