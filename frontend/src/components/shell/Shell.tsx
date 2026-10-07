import { Rail } from './Rail'
import { useEffect } from 'react'
import { GuardianPet } from './GuardianPet'
import { WorkView } from '../work/WorkView'
import { ConnectionBanner } from './ConnectionBanner'
import { ProtectionSetupModal } from '../settings/ProtectionSetupModal'
import { HomeView } from '../home/HomeView'
import { PolicyView } from '../policy/PolicyView'
import { AuditView } from '../audit/AuditView'
import { SettingsView } from '../settings/SettingsView'
import { EvidenceReviewModal } from '../audit/EvidenceReviewModal'
import { LensFilters } from '../common/LensFilters'
import { useActiveRunReconciliation } from '../../hooks/useActiveRunReconciliation'
import { useShellStore, type ShellView } from '../../state/shellStore'

export function Shell() {
  useActiveRunReconciliation()
  const { activeView, setView, setActiveRun } = useShellStore()
  useEffect(() => {
    const navigate = (event: Event) => {
      const detail = (event as CustomEvent<{ view: ShellView; sessionId?: string }>).detail
      if (!detail || !['home', 'work', 'history', 'policy', 'settings'].includes(detail.view)) return
      if (detail.sessionId) setActiveRun(detail.sessionId)
      setView(detail.view)
    }
    window.addEventListener('aia:navigate', navigate)
    return () => window.removeEventListener('aia:navigate', navigate)
  }, [setView, setActiveRun])

  function viewClass(view: ShellView, flush = false) {
    return `app-view${flush ? ' is-flush' : ''}${activeView === view ? '' : ' is-hidden'}`
  }

  return (
    <div className="app-root">
      <LensFilters />
      <ConnectionBanner />
      <div className="app-body">
        <Rail />
        <main className="app-main">
          {/* All views stay mounted and are toggled with CSS, not conditional
              rendering, so switching views keeps the live Codex conversation
              connection and the guardian status. */}
          <section className={viewClass('home')} aria-label="홈">
            <HomeView />
          </section>
          <section className={viewClass('work', true)} aria-label="작업창">
            <WorkView />
          </section>
          <section className={viewClass('policy')} aria-label="정책">
            <PolicyView />
          </section>
          <section className={viewClass('history')} aria-label="기록">
            <AuditView />
          </section>
          <section className={viewClass('settings')} aria-label="설정">
            <SettingsView />
          </section>
        </main>
      </div>
      <ProtectionSetupModal />
      <EvidenceReviewModal />
      <GuardianPet />
    </div>
  )
}
