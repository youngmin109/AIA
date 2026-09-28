import { Shell } from './components/shell/Shell'
import { ShellStoreProvider } from './state/ShellStoreProvider'

function App() {
  return (
    <ShellStoreProvider>
      <Shell />
    </ShellStoreProvider>
  )
}

export default App
