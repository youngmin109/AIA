import { Sidebar } from './Sidebar'
import { Topbar } from './Topbar'
import { ActiveRunPane } from './ActiveRunPane'
import { RightPanel } from './RightPanel'
import { StatusBar } from './StatusBar'
import { ProtectionSetupModal } from '../settings/ProtectionSetupModal'
import { DashboardView } from '../dashboard/DashboardView'
import { PolicyView } from '../policy/PolicyView'
import { AuditView } from '../audit/AuditView'
import { EvidenceReviewModal } from '../audit/EvidenceReviewModal'
import { useActiveRunReconciliation } from '../../hooks/useActiveRunReconciliation'
import { useShellStore, type ShellView } from '../../state/shellStore'

export function Shell() {
  useActiveRunReconciliation()
  const { activeView } = useShellStore()

  function viewClass(view: ShellView) {
    return `main-column-view${activeView === view ? '' : ' is-hidden'}`
  }

  return (
    <div className="shell-root">
      <div className="shell-body">
        <Sidebar />
        <div className="main-column">
          <Topbar />
          {/* All views stay mounted and are toggled with CSS, not
              conditional rendering, so switching views preserves the live
              Codex conversation connection and Guardian status. */}
          <div className={viewClass('dashboard')}>
            <DashboardView />
          </div>
          <div className={viewClass('policy')}>
            <PolicyView />
          </div>
          <div className={viewClass('audit')}>
            <AuditView />
          </div>
          <div className={viewClass('terminal')}>
            <ActiveRunPane />
          </div>
        </div>
        <RightPanel />
      </div>
      <StatusBar />
      <ProtectionSetupModal />
      <EvidenceReviewModal />
    </div>
  )
}
