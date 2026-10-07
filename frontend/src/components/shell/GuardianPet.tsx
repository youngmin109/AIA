import { useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent, type MouseEvent, type PointerEvent } from 'react'
import { GuardianAvatar } from '../common/GuardianAvatar'
import { useGuardianState } from '../../hooks/useGuardianState'
import { useRunStatus } from '../../hooks/useRunStatus'
import { useShellStore } from '../../state/shellStore'
import { normalizePetPosition, petPixels, petPosition, readPetPosition, savePetPosition, type PetPosition } from '../../api/petPreference'
import { GuardianGuide, type GuideTopic } from './GuardianGuide'
import { readPetSize, petPixelSize } from '../../api/petSizePreference'

const DRAG_THRESHOLD = 4
const SPEAK_MS = 6000
const KEY_STEPS: Record<string, [number, number]> = { ArrowLeft: [-0.04, 0], ArrowRight: [0.04, 0], ArrowUp: [0, -0.04], ArrowDown: [0, 0.04] }

function viewport() {
  return { width: window.innerWidth, height: window.innerHeight }
}

/** The guardian floats over the app like a pet: drag it anywhere, click it for help.
 *  It speaks briefly when its state changes. It explains; it never approves, blocks, or restores. */
export function GuardianPet() {
  const { activeRunId } = useShellStore()
  const { data: status } = useRunStatus(activeRunId, { enabled: Boolean(activeRunId) })
  const guardian = useGuardianState()
  const [petSize, setPetSize] = useState(readPetSize)
  const pixels = petPixelSize(petSize)
  const [guideTopic, setGuideTopic] = useState<GuideTopic | null>(null)
  const [position, setPosition] = useState<PetPosition>(readPetPosition)
  const [dragging, setDragging] = useState(false)
  const [quietHeadline, setQuietHeadline] = useState('')
  const button = useRef<HTMLButtonElement>(null)
  const placed = useRef({ left: 0, top: 0 })
  const drag = useRef<{ pointer: number; x: number; y: number; left: number; top: number; moved: boolean } | null>(null)
  const dropped = useRef(false)
  const needsApproval = guardian.label === '사용자 확인'

  function place(left: number, top: number) {
    placed.current = { left, top }
    button.current?.style.setProperty('--pet-x', `${left}px`)
    button.current?.style.setProperty('--pet-y', `${top}px`)
  }

  useLayoutEffect(() => {
    function fit() {
      const { left, top } = petPixels(position, viewport(), pixels)
      place(left, top)
    }
    fit()
    window.addEventListener('resize', fit)
    return () => window.removeEventListener('resize', fit)
  }, [position, pixels])

  useEffect(() => {
    const updateSize = () => setPetSize(readPetSize())
    window.addEventListener('aia:pet-size-changed', updateSize)
    window.addEventListener('storage', updateSize)
    return () => { window.removeEventListener('aia:pet-size-changed', updateSize); window.removeEventListener('storage', updateSize) }
  }, [])

  // A new headline shows the speech bubble for a few seconds.
  useEffect(() => {
    const timer = setTimeout(() => setQuietHeadline(guardian.headline), SPEAK_MS)
    return () => clearTimeout(timer)
  }, [guardian.headline])

  function settle(next: PetPosition) {
    setPosition(next)
    savePetPosition(next)
  }

  function onPointerDown(event: PointerEvent<HTMLButtonElement>) {
    if (event.button !== 0) return
    dropped.current = false
    drag.current = { pointer: event.pointerId, x: event.clientX, y: event.clientY, ...placed.current, moved: false }
    event.currentTarget.setPointerCapture(event.pointerId)
  }

  function onPointerMove(event: PointerEvent<HTMLButtonElement>) {
    const current = drag.current
    if (!current || current.pointer !== event.pointerId) return
    const dx = event.clientX - current.x
    const dy = event.clientY - current.y
    if (!current.moved) {
      if (Math.hypot(dx, dy) < DRAG_THRESHOLD) return
      current.moved = true
      setDragging(true)
    }
    const { left, top } = petPixels(petPosition({ left: current.left + dx, top: current.top + dy }, viewport(), pixels), viewport(), pixels)
    place(left, top)
  }

  function onPointerEnd(event: PointerEvent<HTMLButtonElement>) {
    const current = drag.current
    if (!current || current.pointer !== event.pointerId) return
    drag.current = null
    if (!current.moved) return
    dropped.current = true
    setDragging(false)
    settle(petPosition(placed.current, viewport(), pixels))
  }

  function onClick(event: MouseEvent<HTMLButtonElement>) {
    // A drop is not a click; Enter or Space (detail 0) always opens the help.
    if (dropped.current && event.detail !== 0) {
      dropped.current = false
      return
    }
    const ended = ['COMPLETED', 'ABORTED'].includes(status?.session?.status ?? '')
    setGuideTopic(!activeRunId ? 'start' : guardian.state === 'blocked' || needsApproval ? 'safety' : ended ? 'recovery' : 'start')
  }

  function onKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    const step = KEY_STEPS[event.key]
    if (!step) return
    event.preventDefault()
    settle(normalizePetPosition({ x: position.x + step[0], y: position.y + step[1] }))
  }

  const speaking = needsApproval || guardian.headline !== quietHeadline
  const classes = ['guardian-pet', `is-${guardian.state}`]
  if (dragging) classes.push('is-dragging')
  if (speaking) classes.push('is-speaking')
  if (position.x < 0.5) classes.push('is-left')
  if (position.y < 0.3) classes.push('is-top')

  return (
    <>
      <button
        ref={button}
        type="button"
        className={classes.join(' ')}
        aria-label={`아이아 가디언 도움말 · ${guardian.label}. 방향키로 옮길 수 있어요`}
        aria-expanded={guideTopic !== null}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerEnd}
        onPointerCancel={onPointerEnd}
        onClick={onClick}
        onKeyDown={onKeyDown}
      >
        <span className="guardian-pet-bubble" aria-hidden="true"><b>{guardian.label}</b>{guardian.headline}</span>
        <GuardianAvatar state={guardian.state} alt="" size="pet" />
      </button>
      {guideTopic && <GuardianGuide guardian={guardian} initialTopic={guideTopic} side={position.x < 0.5 ? 'left' : 'right'} onClose={() => setGuideTopic(null)} />}
    </>
  )
}
