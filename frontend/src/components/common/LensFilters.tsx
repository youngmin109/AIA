import { LENS_KINDS, displacementMap, rimMask, type LensKind } from '../../api/lensMap'

const REFRACT = 70 // edge displacement in px; colour channels split slightly for a prism edge
const CHANNELS: Array<[string, number, string]> = [
  ['r', REFRACT, '1 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 1 0'],
  ['g', REFRACT * 0.94, '0 0 0 0 0  0 1 0 0 0  0 0 0 0 0  0 0 0 1 0'],
  ['b', REFRACT * 0.88, '0 0 0 0 0  0 0 0 0 0  0 0 1 0 0  0 0 0 1 0'],
]

/**
 * SVG filters used as backdrop-filter by the four accent panels (Chromium/WebView2).
 * Purely visual; the settings "유리 효과" switch turns them off through CSS.
 */
export function LensFilters() {
  return (
    <svg className="lens-defs" aria-hidden="true" width="0" height="0" focusable="false">
      {(Object.keys(LENS_KINDS) as LensKind[]).map(kind => {
        const [width, height, radius, bezel] = LENS_KINDS[kind]
        return (
          <filter key={kind} id={`aia-lens-${kind}`} x="0" y="0" width="1" height="1" colorInterpolationFilters="sRGB">
            <feImage href={displacementMap(width, height, bezel)} preserveAspectRatio="none" result="map" />
            <feImage href={rimMask(width, height, radius, bezel)} preserveAspectRatio="none" result="rim" />
            <feGaussianBlur in="SourceGraphic" stdDeviation="24" edgeMode="duplicate" result="frost" />
            {CHANNELS.map(([name, scale, matrix]) => [
              <feDisplacementMap key={`d${name}`} in="SourceGraphic" in2="map" scale={scale} xChannelSelector="R" yChannelSelector="G" result={`d${name}`} />,
              <feColorMatrix key={`c${name}`} in={`d${name}`} type="matrix" values={matrix} result={name} />,
            ])}
            <feBlend in="r" in2="g" mode="screen" result="rg" />
            <feBlend in="rg" in2="b" mode="screen" result="lens" />
            <feGaussianBlur in="lens" stdDeviation="2.9" result="blurred" />
            <feColorMatrix in="blurred" type="matrix" values="1.12 0 0 0 0.02  0 1.12 0 0 0.02  0 0 1.12 0 0.02  0 0 0 1 0" result="soft" />
            <feComposite in="soft" in2="rim" operator="in" result="edge" />
            <feMerge>
              <feMergeNode in="frost" />
              <feMergeNode in="edge" />
            </feMerge>
          </filter>
        )
      })}
    </svg>
  )
}
