export function observedCountLabel(available: boolean | undefined, count: number | null | undefined): string {
  if (available !== true || typeof count !== 'number' || !Number.isSafeInteger(count) || count < 0) {
    return '확인 불가'
  }
  return `${count}개`
}
