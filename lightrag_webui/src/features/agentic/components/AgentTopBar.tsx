import { useEffect, useState } from 'react'
import { useAgenticStore } from '../stores/agenticStore'
import { agentClient } from '../../../api/agent'
import { DatabaseIcon, CpuIcon, BookOpenIcon, ActivityIcon } from 'lucide-react'

/** True while the gateway reaches the IoT service (checked at start, then every 30 s). */
function useIotAvailable(): boolean {
  const [available, setAvailable] = useState(false)
  useEffect(() => {
    if (!agentClient.live) return
    let cancelled = false
    const check = () =>
      agentClient.fetchHealth().then(
        (h) => !cancelled && setAvailable(Boolean(h.backends?.iot?.ok)),
        () => !cancelled && setAvailable(false)
      )
    check()
    const id = setInterval(check, 30000)
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [])
  return available
}

export default function AgentTopBar() {
  const { knowledgeDrawerOpen, setKnowledgeDrawerOpen, documents } = useAgenticStore()
  const vectorizedCount = documents.filter((d) => d.indexStatus === 'vectorized').length
  const iotAvailable = useIotAvailable()

  return (
    <header
      className="ag-topbar flex items-center justify-between px-4 shrink-0"
      style={{ height: 56, background: '#1E293B', borderBottom: '1px solid #0F172A' }}
    >
      {/* Left: Brand */}
      <div className="flex items-center gap-3 min-w-0">
        <div className="flex items-center gap-2">
          <div
            className="flex items-center justify-center rounded"
            style={{ width: 28, height: 28, background: '#00A896', boxShadow: '0 0 10px #00A89680' }}
          >
            <CpuIcon size={16} color="#FFFFFF" />
          </div>
          <div className="leading-tight">
            <div className="font-bold tracking-wide" style={{ fontSize: 14, color: '#F1F5F9', fontFamily: 'Inter, sans-serif' }}>
              DENSO Monozukuri Intelligent Hub
            </div>
            <div style={{ fontSize: 11, color: '#94A3B8', fontFamily: 'Roboto Mono, monospace' }}>
              Line A – CNC Station
            </div>
          </div>
        </div>
      </div>

      {/* Center: Status indicators */}
      <div className="flex items-center gap-4">
        <StatusPill label="MQTT" sublabel="Live" color="#00A896" pulse />
        <StatusPill label="PLC Bridge" sublabel="Online" color="#10B981" pulse />
        <StatusPill label="OPC-UA" sublabel="Connected" color="#10B981" />
      </div>

      {/* Right: IoT dashboard + Knowledge Hub + User */}
      <div className="flex items-center gap-3">
        {iotAvailable && (
          <a
            id="iot-dashboard-link"
            href={agentClient.dashboardUrl()}
            target="_blank"
            rel="noopener noreferrer"
            aria-label="Mở dashboard giám sát bệ thử trong tab mới"
            className="flex items-center gap-2 rounded px-3 py-1.5 font-medium transition-all hover:bg-[#475569] focus-visible:outline-2 focus-visible:outline-[#00A896]"
            style={{ fontSize: 13, background: '#334155', color: '#CBD5E1', border: '1px solid #475569', fontFamily: 'Inter, sans-serif' }}
          >
            <ActivityIcon size={14} />
            <span>Giám sát bệ thử ↗</span>
          </a>
        )}
        <button
          id="knowledge-hub-button"
          aria-label={`Knowledge Hub, ${vectorizedCount} documents`}
          onClick={() => setKnowledgeDrawerOpen(!knowledgeDrawerOpen)}
          className="flex items-center gap-2 rounded px-3 py-1.5 font-medium transition-all focus-visible:outline-2 focus-visible:outline-[#00A896]"
          style={{
            fontSize: 13,
            background: knowledgeDrawerOpen ? '#00A896' : '#334155',
            color: knowledgeDrawerOpen ? '#FFFFFF' : '#CBD5E1',
            border: '1px solid #475569',
            fontFamily: 'Inter, sans-serif',
          }}
        >
          <BookOpenIcon size={14} />
          <span>Knowledge Hub</span>
          <span
            className="rounded px-1.5 py-0.5 font-bold"
            style={{ fontSize: 10, background: knowledgeDrawerOpen ? '#FFFFFF30' : '#00A89630', color: knowledgeDrawerOpen ? '#FFFFFF' : '#00A896' }}
          >
            {vectorizedCount}
          </span>
        </button>

        <div
          className="flex items-center gap-2 rounded px-3 py-1.5"
          style={{ background: '#334155', border: '1px solid #475569' }}
        >
          <DatabaseIcon size={13} style={{ color: '#94A3B8' }} />
          <span style={{ fontSize: 12, color: '#CBD5E1', fontFamily: 'Roboto Mono, monospace' }}>
            OPR-01
          </span>
          <div className="size-2 rounded-full" style={{ background: '#10B981' }} />
        </div>
      </div>
    </header>
  )
}

function StatusPill({
  label,
  sublabel,
  color,
  pulse,
}: {
  label: string
  sublabel: string
  color: string
  pulse?: boolean
}) {
  return (
    <div className="flex items-center gap-1.5">
      <div className="relative flex items-center justify-center" style={{ width: 8, height: 8 }}>
        <div className="rounded-full size-2" style={{ background: color }} />
        {pulse && (
          <div
            className="absolute rounded-full size-3 animate-ping"
            style={{ background: color, opacity: 0.4, animationDuration: '2s' }}
          />
        )}
      </div>
      <div className="leading-tight">
        <div className="font-medium" style={{ fontSize: 10, color: '#94A3B8', fontFamily: 'Roboto Mono, monospace' }}>
          {label}
        </div>
        <div className="font-bold" style={{ fontSize: 10, color, fontFamily: 'Roboto Mono, monospace' }}>
          {sublabel}
        </div>
      </div>
    </div>
  )
}
