import { useAgenticStore } from '../stores/agenticStore'
import type { Incident, Conversation, SidebarFilter } from '../types/agentic'
import { AlertTriangleIcon, MessageSquareIcon } from 'lucide-react'
import { cn } from '@/lib/utils'

const FILTER_LABELS: Record<SidebarFilter, string> = {
  all: 'All',
  alerts: 'Automated Alerts',
  qa: 'Technical Q&A',
}

const SEVERITY_COLOR: Record<string, string> = {
  critical: '#EF4444',
  high: '#F59E0B',
  medium: '#3B82F6',
  low: '#10B981',
  info: '#6B7280',
}

const STATUS_LABEL: Record<string, string> = {
  active: 'Active',
  awaiting_approval: 'Awaiting Approval',
  resolved: 'Resolved',
  acknowledged: 'Acknowledged',
  closed: 'Closed',
}

function IncidentCardComp({
  incident,
  conversation,
  isActive,
  onClick,
}: {
  incident: Incident
  conversation: Conversation
  isActive: boolean
  onClick: () => void
}) {
  const isUnresolved = incident.status === 'active' || incident.status === 'awaiting_approval'
  const sevColor = SEVERITY_COLOR[incident.severity] ?? '#6B7280'

  const ts = new Date(incident.timestamp)
  const timeStr = ts.toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' })
  const dateStr = ts.toLocaleDateString('vi-VN', { day: '2-digit', month: '2-digit' })

  return (
    <button
      id={`incident-card-${incident.id}`}
      aria-label={`Incident ${incident.id}: ${incident.alarm}, severity ${incident.severity}, status ${STATUS_LABEL[incident.status]}`}
      aria-pressed={isActive}
      onClick={onClick}
      className={cn(
        'w-full text-left px-3 py-2.5 rounded transition-all focus-visible:outline-2 focus-visible:outline-[#00A896] relative overflow-hidden',
        isActive ? '' : 'hover:bg-[#1C2541]/80'
      )}
      style={{
        background: isActive ? '#1C2541' : 'transparent',
        borderLeft: `3px solid ${isUnresolved ? sevColor : '#3A506B'}`,
        marginBottom: 2,
      }}
    >
      {/* Pulse overlay for unresolved */}
      {isUnresolved && (
        <div
          className="absolute inset-0 pointer-events-none rounded animate-pulse"
          style={{ background: `${sevColor}08`, animationDuration: '2.5s' }}
        />
      )}

      <div className="flex items-start justify-between gap-2 relative">
        <div className="flex items-center gap-1.5 min-w-0 flex-1">
          <AlertTriangleIcon
            size={12}
            style={{ color: sevColor, flexShrink: 0, opacity: isUnresolved ? 1 : 0.5 }}
          />
          <span
            className="text-xs font-semibold truncate"
            style={{ color: isUnresolved ? '#e2e8f0' : '#8a9ab5', fontFamily: 'Inter, sans-serif' }}
          >
            {incident.device}
          </span>
        </div>
        <span
          className="text-[10px] shrink-0"
          style={{ color: '#8a9ab5', fontFamily: 'Roboto Mono, monospace' }}
        >
          {timeStr}
          <br />
          {dateStr}
        </span>
      </div>

      <div
        className="text-xs mt-0.5 leading-snug"
        style={{ color: isUnresolved ? '#cbd5e1' : '#64748b', fontFamily: 'Roboto Mono, monospace' }}
      >
        {incident.alarm}
      </div>

      <div className="flex items-center gap-2 mt-1">
        <span
          className="text-[10px] rounded px-1.5 py-0.5 font-medium uppercase tracking-wide"
          style={{
            background: `${sevColor}20`,
            color: sevColor,
            fontFamily: 'Roboto Mono, monospace',
          }}
        >
          {incident.severity}
        </span>
        <span
          className="text-[10px]"
          style={{
            color: isUnresolved ? sevColor : '#64748b',
            fontFamily: 'Roboto Mono, monospace',
          }}
        >
          {STATUS_LABEL[incident.status] ?? incident.status}
        </span>
      </div>

      {conversation.agentState === 'waiting_hitl' && (
        <div
          className="text-[10px] mt-1 font-bold animate-pulse"
          style={{ color: '#F59E0B', fontFamily: 'Roboto Mono, monospace' }}
        >
          ⏳ AWAITING APPROVAL
        </div>
      )}
    </button>
  )
}

function QACardComp({
  conversation,
  isActive,
  onClick,
}: {
  conversation: Conversation
  isActive: boolean
  onClick: () => void
}) {
  const ts = new Date(conversation.timestamp)
  const timeStr = ts.toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' })
  const dateStr = ts.toLocaleDateString('vi-VN', { day: '2-digit', month: '2-digit' })

  return (
    <button
      id={`qa-card-${conversation.id}`}
      aria-label={`Q&A: ${conversation.title}`}
      aria-pressed={isActive}
      onClick={onClick}
      className={cn(
        'w-full text-left px-3 py-2.5 rounded transition-all focus-visible:outline-2 focus-visible:outline-[#00A896]',
        isActive ? '' : 'hover:bg-[#1C2541]/80'
      )}
      style={{
        background: isActive ? '#1C2541' : 'transparent',
        borderLeft: '3px solid #3A506B',
        marginBottom: 2,
      }}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-1.5 min-w-0 flex-1">
          <MessageSquareIcon size={11} style={{ color: '#00A896', flexShrink: 0 }} />
          <span
            className="text-xs font-medium truncate"
            style={{ color: '#cbd5e1', fontFamily: 'Inter, sans-serif' }}
          >
            {conversation.title}
          </span>
        </div>
        <span
          className="text-[10px] shrink-0"
          style={{ color: '#8a9ab5', fontFamily: 'Roboto Mono, monospace' }}
        >
          {timeStr}
          <br />
          {dateStr}
        </span>
      </div>
    </button>
  )
}

export default function IncidentSidebar() {
  const { sidebarFilter, setSidebarFilter, incidents, conversations, activeConversationId, setActiveConversationId } =
    useAgenticStore()

  const unresolvedCount = incidents.filter(
    (i) => i.status === 'active' || i.status === 'awaiting_approval'
  ).length

  // Build display list based on filter
  const displayItems = conversations.filter((conv) => {
    if (sidebarFilter === 'alerts') return conv.type === 'incident'
    if (sidebarFilter === 'qa') return conv.type === 'manual'
    return true
  })

  return (
    <aside
      className="flex flex-col shrink-0 overflow-hidden"
      style={{
        width: '25%',
        minWidth: 300,
        background: '#0B132B',
        borderRight: '1px solid #3A506B',
      }}
    >
      {/* Sidebar Header */}
      <div className="px-4 pt-3 pb-2 shrink-0" style={{ borderBottom: '1px solid #3A506B' }}>
        <div className="flex items-center justify-between mb-2">
          <span className="text-xs font-semibold uppercase tracking-widest" style={{ color: '#8a9ab5', fontFamily: 'Roboto Mono, monospace' }}>
            Sessions
          </span>
          {unresolvedCount > 0 && (
            <span
              className="text-[10px] font-bold px-1.5 py-0.5 rounded animate-pulse"
              style={{ background: '#EF444420', color: '#EF4444', fontFamily: 'Roboto Mono, monospace' }}
            >
              {unresolvedCount} UNRESOLVED
            </span>
          )}
        </div>

        {/* Filter tabs */}
        <div className="flex gap-1">
          {(Object.keys(FILTER_LABELS) as SidebarFilter[]).map((f) => (
            <button
              key={f}
              id={`sidebar-filter-${f}`}
              aria-label={`Filter: ${FILTER_LABELS[f]}`}
              aria-pressed={sidebarFilter === f}
              onClick={() => setSidebarFilter(f)}
              className="flex-1 rounded text-center text-[10px] font-medium py-1 px-1 transition-all focus-visible:outline-2 focus-visible:outline-[#00A896]"
              style={{
                background: sidebarFilter === f ? '#00A896' : '#1C2541',
                color: sidebarFilter === f ? '#0B132B' : '#8a9ab5',
                fontFamily: 'Inter, sans-serif',
                border: '1px solid #3A506B',
              }}
            >
              {FILTER_LABELS[f]}
            </button>
          ))}
        </div>
      </div>

      {/* Session List */}
      <div className="flex-1 overflow-y-auto scrollbar-thin px-2 py-2">
        {displayItems.length === 0 && (
          <div className="text-center py-8 text-xs" style={{ color: '#3A506B', fontFamily: 'Roboto Mono, monospace' }}>
            No sessions
          </div>
        )}
        {displayItems.map((conv) => {
          const incident = conv.incidentId ? incidents.find((i) => i.id === conv.incidentId) : undefined
          const isActive = conv.id === activeConversationId

          if (conv.type === 'incident' && incident) {
            return (
              <IncidentCardComp
                key={conv.id}
                incident={incident}
                conversation={conv}
                isActive={isActive}
                onClick={() => setActiveConversationId(conv.id)}
              />
            )
          }
          return (
            <QACardComp
              key={conv.id}
              conversation={conv}
              isActive={isActive}
              onClick={() => setActiveConversationId(conv.id)}
            />
          )
        })}
      </div>
    </aside>
  )
}
