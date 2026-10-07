import { useState } from 'react'
import { useNow } from '../../hooks/useElapsed'
import { resetLabel, tokensLabel, usageChip, windowLabel, type Usage } from '../../api/usageView'

/** Remaining Codex usage, read from Codex itself; hidden when Codex reports none. */
export function UsageChip({ usage }: { usage: Usage }) {
  const [open, setOpen] = useState(false)
  const now = useNow(open, 30_000)
  const chip = usageChip(usage)
  if (!chip) return null
  const tokens = tokensLabel(usage.tokens)
  return (
    <span className="usage-chip">
      <button type="button" className={`chip is-small${chip.low ? ' is-warn' : ''}`} aria-expanded={open} onClick={() => setOpen(value => !value)}>
        {chip.text}
      </button>
      {open && (
        <span className="usage-pop glass-card" role="dialog" aria-label="Codex 사용량">
          {(usage.limits?.windows ?? []).map((window, index) => (
            <span key={index} className="usage-row">
              <strong>{windowLabel(window.window_minutes)} 한도 · {100 - window.used_percent}% 남음</strong>
              <svg className="startup-meter" viewBox="0 0 100 4" preserveAspectRatio="none" aria-hidden="true">
                <rect className="startup-meter-track" width="100" height="4" rx="2" />
                <rect className="startup-meter-fill" width={window.used_percent} height="4" rx="2" />
              </svg>
              {resetLabel(window.resets_at, now) && <small className="muted">{resetLabel(window.resets_at, now)}</small>}
            </span>
          ))}
          {usage.limits?.reached && <small className="warning-text">Codex가 사용 한도에 닿았다고 알렸어요.</small>}
          {tokens && <small className="muted">{tokens}</small>}
          <small className="faint-note">Codex가 알려준 값이에요. AIA는 사용량을 바꾸지 않아요.</small>
        </span>
      )}
    </span>
  )
}
