import { Shell } from './components/shell/Shell'
import { ShellStoreProvider } from './state/shellStore'

function App() {
  return (
    <ShellStoreProvider>
      <Shell />
    </ShellStoreProvider>
  )
}

export default App
