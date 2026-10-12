import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { DesktopGuardian } from './components/shell/DesktopGuardian'
import { readMotionPreference } from './api/motionPreference'
import { readTintPreference } from './api/tintPreference'
import { readGlassPreference } from './api/glassPreference'
import { readPetPreference } from './api/petPreference'
import { readPetSize, displayPetSize } from './api/petSizePreference'
import { startDesktopHeartbeat, syncTitleBar, syncDesktopGuardian } from './desktopBridge'

// One dark glass theme (EPIC-020); the viewer only picks a color tint.
document.documentElement.dataset.tint = readTintPreference()
document.documentElement.dataset.glass = readGlassPreference()
document.documentElement.dataset.motion = readMotionPreference()
document.documentElement.dataset.pet = readPetPreference()
displayPetSize(readPetSize())
const desktopGuardian = new URLSearchParams(window.location.search).get('surface') === 'guardian'
if (desktopGuardian) document.documentElement.dataset.surface = 'guardian'
else startDesktopHeartbeat()
// The desktop bridge appears after pywebview injects it; match the caption then.
window.addEventListener('pywebviewready', () => {
  if (!desktopGuardian) { syncTitleBar(readTintPreference()); syncDesktopGuardian() }
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    {desktopGuardian ? <DesktopGuardian /> : <App />}
  </StrictMode>,
)
