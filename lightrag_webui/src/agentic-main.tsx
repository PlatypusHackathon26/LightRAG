// Agentic Copilot entry point — standalone, no LightRAG auth required in DEMO mode
import '@/migrations/runSettingsStorageSplit'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import './features/agentic/agentic.css'
import { AgenticWorkspace } from './features/agentic'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <AgenticWorkspace />
  </StrictMode>
)
