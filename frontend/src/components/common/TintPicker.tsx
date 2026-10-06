import { useState } from 'react'
import { TINT_OPTIONS, applyTintPreference, readTintPreference, type TintPreference } from '../../api/tintPreference'

/** Color theme swatches (violet, indigo, teal) for the single dark glass theme. */
export function TintPicker() {
  const [tint, setTint] = useState<TintPreference>(readTintPreference)

  function choose(next: TintPreference) {
    applyTintPreference(next)
    setTint(next)
  }

  return (
    <div className="tint-picker" role="group" aria-label="색상 테마">
      {TINT_OPTIONS.map((option) => (
        <button
          key={option.value}
          type="button"
          className={`tint-swatch is-${option.value}`}
          aria-pressed={tint === option.value}
          aria-label={option.label}
          title={option.label}
          onClick={() => choose(option.value)}
        />
      ))}
    </div>
  )
}
