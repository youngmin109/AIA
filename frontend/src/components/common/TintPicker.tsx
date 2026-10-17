import { useEffect, useState } from 'react'
import { TINT_OPTIONS, applyTintPreference, readTintPreference, type TintPreference } from '../../api/tintPreference'
import { syncTitleBar } from '../../desktopBridge'
import { UI_PREFERENCE_RESTORED_EVENT } from '../../api/preferenceSync'

/** Color theme swatches (violet, indigo, teal) for the single dark glass theme. */
export function TintPicker() {
  const [tint, setTint] = useState<TintPreference>(readTintPreference)

  useEffect(() => {
    const restoreTint = (event: Event) => {
      if ((event as CustomEvent<string>).detail !== 'aia.tint') return
      const value = readTintPreference()
      setTint(value)
      syncTitleBar(value)
    }
    window.addEventListener(UI_PREFERENCE_RESTORED_EVENT, restoreTint)
    return () => window.removeEventListener(UI_PREFERENCE_RESTORED_EVENT, restoreTint)
  }, [])

  function choose(next: TintPreference) {
    applyTintPreference(next)
    syncTitleBar(next)
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
