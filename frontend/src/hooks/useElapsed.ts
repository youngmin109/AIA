import { useEffect, useState } from 'react'
import { formatElapsed } from '../api/homeStatus'

/** Current time that ticks while `running`; keeps Date.now() out of render. */
export function useNow(running: boolean, intervalMs = 1000): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!running) return
    const timer = window.setInterval(() => setNow(Date.now()), intervalMs)
    return () => window.clearInterval(timer)
  }, [running, intervalMs])
  return now
}

/** "m:ss" between a start time and `now`; null when the start is unknown. */
export function elapsedLabel(startedAt: string | undefined | null, now: number): string | null {
  const start = Date.parse(startedAt ?? '')
  return Number.isNaN(start) ? null : formatElapsed(now - start)
}
