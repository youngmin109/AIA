import { Shell } from './components/shell/Shell'
import { ShellStoreProvider } from './state/ShellStoreProvider'
import { RunListProvider } from './hooks/useRunList'

function App() {
  return (
    <ShellStoreProvider>
      <RunListProvider>
        <Shell />
      </RunListProvider>
    </ShellStoreProvider>
  )
}

export default App
