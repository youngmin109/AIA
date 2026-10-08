import { useNow } from '../../hooks/useElapsed'
import type { StartupView } from '../../api/startupStatus'

/** Which preparation step a protected run is in, so a slow start is never a blank wait. */
export function StartupProgress({ view }: { view: StartupView }) {
  const now = useNow(true)
  const started = Date.parse(view.startedAt ?? '')
  const seconds = Number.isNaN(started) ? null : Math.max(0, Math.round((now - started) / 1000))
  return (
    <div className="startup-progress" role="status">
      <span className="startup-step">{view.index}/{view.total}단계</span>
      <strong>{view.label}{seconds !== null && seconds >= 3 ? ` · ${seconds}초` : ''}</strong>
      {view.detail && <span className="muted">{view.detail}</span>}
      {view.percent !== null && (
        <svg className="startup-meter" viewBox="0 0 100 4" preserveAspectRatio="none" aria-hidden="true">
          <rect className="startup-meter-track" width="100" height="4" rx="2" />
          <rect className="startup-meter-fill" width={view.percent} height="4" rx="2" />
        </svg>
      )}
      {view.largeFolder && <span className="faint-note">파일이 많은 폴더라 시작까지 시간이 걸릴 수 있어요.</span>}
    </div>
  )
}
