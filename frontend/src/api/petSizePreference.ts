export type PetSizePreference = number
export const PET_SIZE_MIN = 70
export const PET_SIZE_MAX = 140
export const PET_SIZE_STEP = 5
/** The pet starts at its smallest so it does not get in the way; the slider makes it bigger. */
export const PET_SIZE_DEFAULT = PET_SIZE_MIN
const LEGACY: Record<string, number> = { small: 80, medium: 100, large: 130 }
export function normalizePetSize(value: string | number | null): PetSizePreference {
  if (typeof value === 'string' && Object.hasOwn(LEGACY, value)) return LEGACY[value]
  const size = value === null || value === '' ? NaN : Number(value)
  return Number.isFinite(size) ? Math.max(PET_SIZE_MIN, Math.min(PET_SIZE_MAX, Math.round(size / PET_SIZE_STEP) * PET_SIZE_STEP)) : PET_SIZE_DEFAULT
}
export function readPetSize(): PetSizePreference {
  try { return normalizePetSize(localStorage.getItem('aia.pet.size')) } catch { return PET_SIZE_DEFAULT }
}
export function displayPetSize(value: PetSizePreference): void {
  document.documentElement.dataset.petSize = String(value)
  document.documentElement.style.setProperty('--browser-pet-size', `${petPixelSize(value)}px`)
}
export function applyPetSize(value: PetSizePreference): void {
  const size = normalizePetSize(value)
  displayPetSize(size)
  try { localStorage.setItem('aia.pet.size', String(size)) } catch { /* keep the in-memory choice */ }
  window.dispatchEvent(new Event('aia:pet-size-changed'))
}
export function petPixelSize(value: PetSizePreference): number {
  return Math.round(104 * value / 100)
}
