import { ActivityBar } from './ActivityBar'
import { Sidebar } from './Sidebar'
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
        <ActivityBar />
        <Sidebar />
        <ActiveRunPane />
        <RightPanel />
      </div>
      <StatusBar />
      <ProtectionSetupModal />
    </div>
  )
}
