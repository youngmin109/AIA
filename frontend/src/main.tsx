import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { readMotionPreference } from './api/motionPreference'
import { readTintPreference } from './api/tintPreference'
import { readGlassPreference } from './api/glassPreference'
import { readPetPreference } from './api/petPreference'
import { startDesktopHeartbeat, syncTitleBar } from './desktopBridge'

// One dark glass theme (EPIC-020); the viewer only picks a color tint.
document.documentElement.dataset.tint = readTintPreference()
document.documentElement.dataset.glass = readGlassPreference()
document.documentElement.dataset.motion = readMotionPreference()
document.documentElement.dataset.pet = readPetPreference()
startDesktopHeartbeat()
// The desktop bridge appears after pywebview injects it; match the caption then.
window.addEventListener('pywebviewready', () => syncTitleBar(readTintPreference()))

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
