import type { ReactNode } from 'react'

/** Centered placeholder for a pane with nothing to show yet. */
export function EmptyState({ title, children }: { title: ReactNode; children?: ReactNode }) {
  return (
    <div className="center-empty-state">
      <strong>{title}</strong>
      {children}
    </div>
  )
}
