import { useEffect, useState } from 'react'
import { useAgenticStore } from '../stores/agenticStore'
import { agentClient } from '../../../api/agent'
import { ActivityIcon, UploadIcon } from 'lucide-react'

const pad = (n: number) => String(n).padStart(2, '0')
const stamp = (d: Date) =>
  `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`

function useClock(): string {
  const [now, setNow] = useState(() => stamp(new Date()))
  useEffect(() => {
    const id = setInterval(() => setNow(stamp(new Date())), 1000)
    return () => clearInterval(id)
  }, [])
  return now
}

export default function AgentTopBar() {
  const { knowledgeDrawerOpen, setKnowledgeDrawerOpen, documents, isLive, liveError } = useAgenticStore()
  const vectorizedCount = documents.filter((d) => d.indexStatus === 'vectorized').length
  const clock = useClock()
  const online = !(isLive && liveError)

  return (
    <header
      className="ag-topbar flex items-center justify-between px-4 shrink-0"
      style={{ height: 48, background: 'rgba(15,23,42,0.8)', borderBottom: '1px solid #1E293B', backdropFilter: 'blur(6px)' }}
    >
      {/* Left: brand */}
      <div className="flex items-center gap-3 min-w-0">
        <span className="relative flex" style={{ width: 10, height: 10 }} aria-hidden>
          <span className="absolute inline-flex h-full w-full rounded-full animate-ping" style={{ background: '#10B981', opacity: 0.6 }} />
          <span className="relative inline-flex rounded-full" style={{ width: 10, height: 10, background: '#10B981' }} />
        </span>
        <h1 className="font-bold uppercase tracking-wider truncate" style={{ fontSize: 16, color: '#F1F5F9', fontFamily: 'Inter, sans-serif' }}>
          <span style={{ color: '#E60012', fontWeight: 900 }}>DENSO</span> AI-Agent 2026
        </h1>
        <span
          className="rounded px-2 py-0.5 shrink-0"
          style={{ fontSize: 10, background: '#1E293B', color: '#94A3B8', border: '1px solid #334155' }}
        >
          IIoT · RAG · HITL
        </span>
      </div>

      {/* Right: status, clock, dashboard, knowledge upload */}
      <div className="flex items-center gap-4" style={{ fontSize: 12, color: '#94A3B8' }}>
        <div className="hidden md:block">
          Hệ thống:{' '}
          <span className="font-medium" style={{ color: online ? '#34D399' : '#F87171' }}>
            {online ? 'TRỰC TUYẾN' : 'MẤT KẾT NỐI'}
          </span>
        </div>
        <div className="hidden lg:block font-mono" style={{ color: '#E2E8F0' }} aria-label="Giờ hệ thống">
          {clock}
        </div>

        {/* Always shown with a live gateway: without Long-agent the gateway answers with its own message. */}
        {agentClient.live && (
          <a
            id="iot-dashboard-link"
            href={agentClient.dashboardUrl()}
            target="_blank"
            rel="noopener noreferrer"
            aria-label="Mở dashboard giám sát nhà xưởng trong tab mới"
            title="Dashboard giám sát nhà xưởng (Long-agent, tab mới)"
            className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 font-medium transition hover:bg-[#1E293B] focus-visible:outline-2 focus-visible:outline-[#06B6D4]"
            style={{ color: '#E2E8F0', border: '1px solid #334155' }}
          >
            <ActivityIcon size={14} />
            <span>Dashboard</span>
          </a>
        )}
        <button
          id="knowledge-hub-button"
          aria-label={`Upfile lên RAG, ${vectorizedCount} tài liệu`}
          aria-pressed={knowledgeDrawerOpen}
          onClick={() => setKnowledgeDrawerOpen(!knowledgeDrawerOpen)}
          className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 font-semibold transition hover:bg-[#06B6D4] focus-visible:outline-2 focus-visible:outline-[#22D3EE]"
          style={{
            background: knowledgeDrawerOpen ? '#06B6D4' : '#0891B2',
            color: '#FFFFFF',
            boxShadow: '0 10px 15px -3px rgba(22,78,99,0.4)',
          }}
        >
          <UploadIcon size={14} />
          <span>Upfile lên RAG</span>
          <span className="rounded px-1.5 font-bold" style={{ fontSize: 10, background: '#FFFFFF30' }}>
            {vectorizedCount}
          </span>
        </button>
      </div>
    </header>
  )
}
