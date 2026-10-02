import { Shell } from './components/shell/Shell'
import { ShellStoreProvider } from './state/ShellStoreProvider'
import { RunStatusProvider } from './hooks/useRunStatus'
import { RunListProvider } from './hooks/useRunList'

function App() {
  return (
    <ShellStoreProvider>
      <RunListProvider>
        <RunStatusProvider><Shell /></RunStatusProvider>
      </RunListProvider>
    </ShellStoreProvider>
  )
}

export default App
