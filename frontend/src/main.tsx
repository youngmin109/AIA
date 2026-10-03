import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { readMotionPreference } from './api/motionPreference'
import { startDesktopHeartbeat } from './desktopBridge'

document.documentElement.dataset.motion = readMotionPreference()
startDesktopHeartbeat()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
