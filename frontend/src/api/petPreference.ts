export type PetPreference = 'on' | 'off'
/** Where the pet sits, as 0..1 across the free area of the window, so it survives resizing. */
export interface PetPosition { x: number; y: number }
interface Viewport { width: number; height: number }
interface PetPixels { left: number; top: number }

/** Matches `.guardian-pet` in glass.css. */
export const PET_SIZE = 104
const EDGE = 12

export function normalizePetPreference(value: string | null): PetPreference {
  return value === 'off' ? 'off' : 'on'
}

export function readPetPreference(): PetPreference {
  try { return normalizePetPreference(localStorage.getItem('aia.pet')) } catch { return 'on' }
}

/** The guardian pet only explains; hiding it changes nothing about protection. */
export function applyPetPreference(value: PetPreference): void {
  document.documentElement.dataset.pet = value
  try { localStorage.setItem('aia.pet', value) } catch { /* keep the in-memory choice */ }
}

function axis(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) ? Math.min(1, Math.max(0, value)) : 1
}

/** Unknown or broken values put the pet back in the bottom-right corner. */
export function normalizePetPosition(value: unknown): PetPosition {
  const position = value && typeof value === 'object' ? value as Record<string, unknown> : {}
  return { x: axis(position.x), y: axis(position.y) }
}

export function readPetPosition(): PetPosition {
  try { return normalizePetPosition(JSON.parse(localStorage.getItem('aia.pet.position') ?? 'null')) } catch { return normalizePetPosition(null) }
}

export function savePetPosition(position: PetPosition): void {
  try { localStorage.setItem('aia.pet.position', JSON.stringify(position)) } catch { /* the pet still stays where it was dropped */ }
}

function span(length: number, size: number): number {
  return Math.max(0, length - size - 2 * EDGE)
}

/** Top-left corner of the pet in pixels; always inside the window. */
export function petPixels(position: PetPosition, viewport: Viewport, size = PET_SIZE): PetPixels {
  return { left: Math.round(EDGE + position.x * span(viewport.width, size)), top: Math.round(EDGE + position.y * span(viewport.height, size)) }
}

/** Inverse of petPixels for a drag; a drop past the edge is clamped to it. */
export function petPosition(pixels: PetPixels, viewport: Viewport, size = PET_SIZE): PetPosition {
  const width = span(viewport.width, size)
  const height = span(viewport.height, size)
  return normalizePetPosition({ x: width ? (pixels.left - EDGE) / width : 0, y: height ? (pixels.top - EDGE) / height : 0 })
}
