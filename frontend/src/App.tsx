import { Shell } from './components/shell/Shell'
import { ShellStoreProvider } from './state/ShellStoreProvider'
import { RunStatusProvider } from './hooks/useRunStatus'
import { RunListProvider } from './hooks/useRunList'
import { ErrorBoundary } from './components/common/ErrorBoundary'

function App() {
  return (
    <ErrorBoundary>
      <ShellStoreProvider>
        <RunListProvider>
          <RunStatusProvider><Shell /></RunStatusProvider>
        </RunListProvider>
      </ShellStoreProvider>
    </ErrorBoundary>
  )
}

export default App
