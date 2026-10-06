/**
 * Displacement maps for the refraction accent (EPIC-020 TASK-017).
 * R drives x, G drives y, 128 is neutral. Pixels inside the bezel sample the
 * backdrop further inward, so shapes bend at the rim like a thick glass edge;
 * the rim mask keeps that sharp band at the edge and the centre stays frosted.
 */

const PROFILE: Array<[number, number]> = [[0, 1], [0.25, 0.5625], [0.5, 0.25], [0.75, 0.0625], [1, 0]]

/** kind: map width, map height, corner radius, bezel — sized near the real panels. */
export const LENS_KINDS = {
  hero: [1200, 340, 32, 40],
  panel: [760, 420, 28, 34],
  dialog: [560, 440, 30, 34],
} as const

export type LensKind = keyof typeof LENS_KINDS

function uri(svg: string): string {
  return `data:image/svg+xml,${encodeURIComponent(svg)}`
}

function stops(fraction: number, channel: 'r' | 'g'): string {
  const color = (value: number) => (channel === 'r' ? `rgb(${value},0,0)` : `rgb(0,${value},0)`)
  const near = PROFILE.map(([u, p]) => `<stop offset='${(u * fraction).toFixed(4)}' stop-color='${color(Math.round(128 + 127 * p))}'/>`)
  const far = [...PROFILE].reverse().map(([u, p]) => `<stop offset='${(1 - u * fraction).toFixed(4)}' stop-color='${color(Math.round(128 - 128 * p))}'/>`)
  return near.join('') + far.join('')
}

export function displacementMap(width: number, height: number, bezel: number): string {
  return uri(
    `<svg xmlns='http://www.w3.org/2000/svg' width='${width}' height='${height}'><defs>`
    + `<linearGradient id='x' x1='0' y1='0' x2='1' y2='0'>${stops(bezel / width, 'r')}</linearGradient>`
    + `<linearGradient id='y' x1='0' y1='0' x2='0' y2='1'>${stops(bezel / height, 'g')}</linearGradient></defs>`
    + `<rect width='${width}' height='${height}' fill='url(#x)'/>`
    + `<rect width='${width}' height='${height}' fill='url(#y)' style='mix-blend-mode:screen'/></svg>`,
  )
}

export function rimMask(width: number, height: number, radius: number, bezel: number): string {
  return uri(
    `<svg xmlns='http://www.w3.org/2000/svg' width='${width}' height='${height}'><defs>`
    + `<filter id='s' x='-20%' y='-20%' width='140%' height='140%'><feGaussianBlur stdDeviation='${(bezel * 0.35).toFixed(1)}'/></filter></defs>`
    + `<rect width='${width}' height='${height}' rx='${radius}' fill='none' stroke='#fff' stroke-width='${(bezel * 1.8).toFixed(1)}' filter='url(#s)'/></svg>`,
  )
}
