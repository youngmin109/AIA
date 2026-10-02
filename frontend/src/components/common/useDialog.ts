import { useEffect, useRef } from 'react'
/** Keyboard focus stays in an open dialog and returns to its trigger. */
export function useDialog(open: boolean, dismiss: () => void) {
  const ref = useRef<HTMLDivElement>(null)
  const dismissRef = useRef(dismiss)
  useEffect(() => { dismissRef.current = dismiss }, [dismiss])
  useEffect(() => {
    if (!open) return
    const previous = document.activeElement as HTMLElement | null
    const focusable = () => Array.from(ref.current?.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), a[href], [tabindex="0"]') ?? []).filter(node => node.getClientRects().length > 0)
    const timer = window.setTimeout(() => focusable()[0]?.focus(), 0)
    function keydown(event: KeyboardEvent) {
      if (event.key === 'Escape') { event.preventDefault(); dismissRef.current(); return }
      if (event.key !== 'Tab') return
      const nodes = focusable()
      const first = nodes[0], last = nodes.at(-1)
      if (!first) { event.preventDefault(); return }
      if (event.shiftKey && (document.activeElement === first || !ref.current?.contains(document.activeElement))) { event.preventDefault(); last?.focus() }
      else if (!event.shiftKey && (document.activeElement === last || !ref.current?.contains(document.activeElement))) { event.preventDefault(); first.focus() }
    }
    document.addEventListener('keydown', keydown)
    return () => { window.clearTimeout(timer); document.removeEventListener('keydown', keydown); previous?.focus() }
  }, [open])
  return ref
}
