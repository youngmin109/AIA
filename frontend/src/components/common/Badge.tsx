import type { HTMLAttributes } from 'react'

export type BadgeTone = 'ok' | 'warn' | 'bad' | 'neutral' | 'accent'
// 'ok' and 'warn' come from statusTone(); only .status-pill.ok has its own style.
export type PillTone = 'good' | 'ok' | 'neutral' | 'warning' | 'warn' | 'bad'

type SpanProps = Omit<HTMLAttributes<HTMLSpanElement>, 'className'>

/** Small status label inside rows and result sections. */
export function Badge({ tone, ...props }: SpanProps & { tone: BadgeTone }) {
  return <span className={`badge is-${tone}`} {...props} />
}

/** Status label in page and card headers. */
export function StatusPill({ tone, ...props }: SpanProps & { tone: PillTone }) {
  return <span className={`status-pill ${tone}`} {...props} />
}
