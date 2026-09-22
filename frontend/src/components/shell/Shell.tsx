import { Sidebar } from './Sidebar'
import { Topbar } from './Topbar'
import { ActiveRunPane } from './ActiveRunPane'
import { RightPanel } from './RightPanel'
import { StatusBar } from './StatusBar'
import { ProtectionSetupModal } from '../settings/ProtectionSetupModal'
import { useActiveRunReconciliation } from '../../hooks/useActiveRunReconciliation'

export function Shell() {
  useActiveRunReconciliation()

  return (
    <div className="shell-root">
      <div className="shell-body">
        <Sidebar />
        <div className="main-column">
          <Topbar />
          <ActiveRunPane />
        </div>
        <RightPanel />
      </div>
      <StatusBar />
      <ProtectionSetupModal />
    </div>
  )
}
