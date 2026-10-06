import AgentTopBar from './components/AgentTopBar'
import IncidentSidebar from './components/IncidentSidebar'
import ChatWorkspace from './components/ChatWorkspace'
import KnowledgeHubDrawer from './components/KnowledgeHubDrawer'
import { useLiveTelemetry } from './hooks/useLiveTelemetry'

export default function AgenticWorkspace() {
  // Drive live telemetry updates
  useLiveTelemetry()

  return (
    <div
      className="flex flex-col overflow-hidden"
      style={{
        height: '100vh',
        width: '100vw',
        background: '#F5F7FA',
        fontFamily: 'Inter, sans-serif',
      }}
    >
      {/* Top bar — fixed 56px */}
      <AgentTopBar />

      {/* Main layout */}
      <div className="flex flex-1 overflow-hidden">
        {/* Left sidebar: 25% min 300px */}
        <IncidentSidebar />

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
