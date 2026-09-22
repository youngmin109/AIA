import { ActivityBar } from './ActivityBar'
import { Sidebar } from './Sidebar'
import { CenterTabs } from './CenterTabs'
import { RightPanel } from './RightPanel'
import { StatusBar } from './StatusBar'
import { ProtectionSetupModal } from '../settings/ProtectionSetupModal'

export function Shell() {
  return (
    <div className="shell-root">
      <div className="shell-body">
        <ActivityBar />
        <Sidebar />
        <CenterTabs />
        <RightPanel />
      </div>
      <StatusBar />
      <ProtectionSetupModal />
    </div>
  )
}
