import { Rail } from './Rail'
import { WorkView } from '../work/WorkView'
import { ConnectionBanner } from './ConnectionBanner'
import { ProtectionSetupModal } from '../settings/ProtectionSetupModal'
import { HomeView } from '../home/HomeView'
import { PolicyView } from '../policy/PolicyView'
import { AuditView } from '../audit/AuditView'
import { SettingsView } from '../settings/SettingsView'
import { EvidenceReviewModal } from '../audit/EvidenceReviewModal'
import { useActiveRunReconciliation } from '../../hooks/useActiveRunReconciliation'
import { useShellStore, type ShellView } from '../../state/shellStore'

export function Shell() {
  useActiveRunReconciliation()
  const { activeView } = useShellStore()

  function viewClass(view: ShellView, flush = false) {
    return `app-view${flush ? ' is-flush' : ''}${activeView === view ? '' : ' is-hidden'}`
  }

  return (
    <div className="app-root">
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
    </div>
  )
}
