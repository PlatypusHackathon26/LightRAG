import { useAgenticStore } from '../stores/agenticStore'
import { DatabaseIcon, CpuIcon, BookOpenIcon } from 'lucide-react'

export default function AgentTopBar() {
  const { knowledgeDrawerOpen, setKnowledgeDrawerOpen, documents } = useAgenticStore()
  const vectorizedCount = documents.filter((d) => d.indexStatus === 'vectorized').length

  return (
    <header
      className="ag-topbar flex items-center justify-between px-4 shrink-0"
      style={{ height: 56, background: '#0B132B', borderBottom: '1px solid #3A506B' }}
    >
      {/* Left: Brand */}
      <div className="flex items-center gap-3 min-w-0">
        <div className="flex items-center gap-2">
          <div
            className="flex items-center justify-center rounded"
            style={{ width: 28, height: 28, background: '#00A896', boxShadow: '0 0 10px #00A89680' }}
          >
            <CpuIcon size={16} color="#0B132B" />
          </div>
          <div className="leading-tight">
            <div className="text-white font-bold text-sm tracking-wide" style={{ fontFamily: 'Inter, sans-serif' }}>
              DENSO Monozukuri Intelligent Hub
            </div>
            <div className="text-xs" style={{ color: '#3A506B', fontFamily: 'Roboto Mono, monospace' }}>
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

      {/* Right: Knowledge Hub + User */}
      <div className="flex items-center gap-3">
        <button
          id="knowledge-hub-button"
          aria-label={`Knowledge Hub, ${vectorizedCount} documents`}
          onClick={() => setKnowledgeDrawerOpen(!knowledgeDrawerOpen)}
          className="flex items-center gap-2 rounded px-3 py-1.5 text-xs font-medium transition-all focus-visible:outline-2 focus-visible:outline-[#00A896]"
          style={{
            background: knowledgeDrawerOpen ? '#00A896' : '#1C2541',
            color: knowledgeDrawerOpen ? '#0B132B' : '#e2e8f0',
            border: '1px solid #3A506B',
            fontFamily: 'Inter, sans-serif',
          }}
        >
          <BookOpenIcon size={14} />
          <span>Knowledge Hub</span>
          <span
            className="rounded px-1.5 py-0.5 text-[10px] font-bold"
            style={{ background: knowledgeDrawerOpen ? '#0B132B20' : '#00A89620', color: '#00A896' }}
          >
            {vectorizedCount}
          </span>
        </button>

        <div
          className="flex items-center gap-2 rounded px-3 py-1.5"
          style={{ background: '#1C2541', border: '1px solid #3A506B' }}
        >
          <DatabaseIcon size={13} style={{ color: '#3A506B' }} />
          <span className="text-xs" style={{ color: '#8a9ab5', fontFamily: 'Roboto Mono, monospace' }}>
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
        <div className="text-[10px] font-medium" style={{ color: '#8a9ab5', fontFamily: 'Roboto Mono, monospace' }}>
          {label}
        </div>
        <div className="text-[10px] font-bold" style={{ color, fontFamily: 'Roboto Mono, monospace' }}>
          {sublabel}
        </div>
      </div>
    </div>
  )
}
