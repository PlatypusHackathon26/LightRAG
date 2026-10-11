import { useEffect } from 'react'
import AgentTopBar from './components/AgentTopBar'
import IncidentSidebar from './components/IncidentSidebar'
import ChatWorkspace from './components/ChatWorkspace'
import KnowledgeHubDrawer from './components/KnowledgeHubDrawer'
import { useLiveTelemetry } from './hooks/useLiveTelemetry'
import { useAgenticStore } from './stores/agenticStore'
import { agentClient } from '@/api/agent'

export default function AgenticWorkspace() {
  // Drive live telemetry updates
  useLiveTelemetry()

  // Live mode: replace the mock documents/incidents with the Agent Gateway's.
  const loadLiveData = useAgenticStore((s) => s.loadLiveData)
  const syncLiveIncidents = useAgenticStore((s) => s.syncLiveIncidents)
  const sidebarOpen = useAgenticStore((s) => s.sidebarOpen)
  useEffect(() => {
    void loadLiveData({ documents: agentClient.fetchDocuments, incidents: agentClient.fetchIncidents })
  }, [loadLiveData])
  // Live mode: alerts raised while the page is open (Long-agent) appear within a few seconds.
  useEffect(() => {
    if (!agentClient.live) return
    const id = setInterval(() => {
      agentClient.fetchIncidents().then(syncLiveIncidents, () => { /* gateway or Long-agent down: keep what is shown */ })
    }, 4000)
    return () => clearInterval(id)
  }, [syncLiveIncidents])

  return (
    <div
      className="flex flex-col overflow-hidden"
      style={{
        height: '100vh',
        width: '100vw',
        background: '#0F172A',
        fontFamily: 'Inter, sans-serif',
      }}
    >
      {/* Top bar — fixed 56px */}
      <AgentTopBar />

      {/* Main layout */}
      <div className="flex flex-1 overflow-hidden">
        {/* Left sidebar: 25%, collapsible from the top bar */}
        {sidebarOpen && <IncidentSidebar />}

        {/* Main workspace: flex-1 */}
        <main className="flex-1 flex flex-col overflow-hidden">
          <ChatWorkspace />
        </main>
      </div>

      {/* Right sliding drawer — overlays workspace, never resizes it */}
      <KnowledgeHubDrawer />
    </div>
  )
}
