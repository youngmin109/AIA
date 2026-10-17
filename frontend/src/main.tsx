import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { DesktopGuardian } from './components/shell/DesktopGuardian'
import { applyMotionPreference, readMotionPreference } from './api/motionPreference'
import { applyTintPreference, readTintPreference } from './api/tintPreference'
import { applyGlassPreference, readGlassPreference } from './api/glassPreference'
import { applyPetPreference, applyPetPosition, readPetPosition, readPetPreference } from './api/petPreference'
import { applyPetSize, readPetSize, displayPetSize } from './api/petSizePreference'
import { restoreUiPreferences } from './api/preferenceSync'
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

// Restore asynchronously so the first screen never waits for the local server.
if (!desktopGuardian) {
  void restoreUiPreferences(key => {
    switch (key) {
      case 'aia.glass': applyGlassPreference(readGlassPreference()); break
      case 'aia.motion': applyMotionPreference(readMotionPreference()); break
      case 'aia.tint': applyTintPreference(readTintPreference()); syncTitleBar(readTintPreference()); break
      case 'aia.pet': applyPetPreference(readPetPreference()); syncDesktopGuardian(); break
      case 'aia.pet.position': applyPetPosition(readPetPosition()); break
      case 'aia.pet.size': applyPetSize(readPetSize()); syncDesktopGuardian(); break
    }
  })
}
