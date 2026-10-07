export type PetSizePreference = 'small' | 'medium' | 'large'
export const PET_SIZE_OPTIONS: Array<[PetSizePreference, string]> = [['small', '작게'], ['medium', '보통'], ['large', '크게']]
export function normalizePetSize(value: string | null): PetSizePreference {
  return value === 'small' || value === 'large' ? value : 'medium'
}
export function readPetSize(): PetSizePreference {
  try { return normalizePetSize(localStorage.getItem('aia.pet.size')) } catch { return 'medium' }
}
export function applyPetSize(value: PetSizePreference): void {
  document.documentElement.dataset.petSize = value
  try { localStorage.setItem('aia.pet.size', value) } catch { /* keep the in-memory choice */ }
  window.dispatchEvent(new Event('aia:pet-size-changed'))
}
export function petPixelSize(value: PetSizePreference): number {
  return { small: 84, medium: 104, large: 136 }[value]
}
