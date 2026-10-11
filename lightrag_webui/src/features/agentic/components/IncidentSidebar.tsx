import type React from 'react'
import { useAgenticStore } from '../stores/agenticStore'
import type { Incident, Conversation, SidebarFilter } from '../types/agentic'
import { AlertTriangleIcon, MessageSquareIcon, PlusIcon, Trash2Icon } from 'lucide-react'
import { cn } from '@/lib/utils'
import { historyGroup, isBlank } from '../chatHistory'
import { isHandled } from '../alertDismissal'

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
  info: '#94A3B8',
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
  onDelete,
}: {
  incident: Incident
  conversation: Conversation
  isActive: boolean
  onClick: () => void
  onDelete?: () => void
}) {
  const isUnresolved = incident.status === 'active' || incident.status === 'awaiting_approval'
  const sevColor = SEVERITY_COLOR[incident.severity] ?? '#94A3B8'

  const ts = new Date(incident.timestamp)
  const timeStr = ts.toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' })
  const dateStr = ts.toLocaleDateString('vi-VN', { day: '2-digit', month: '2-digit' })

  return (
    <div className="group relative">
      <button
        id={`incident-card-${incident.id}`}
        aria-label={`Incident ${incident.id}: ${incident.alarm}, severity ${incident.severity}, status ${STATUS_LABEL[incident.status]}`}
        aria-pressed={isActive}
        onClick={onClick}
        className={cn(
          'w-full text-left px-3 py-2.5 rounded transition-all focus-visible:outline-2 focus-visible:outline-[#06B6D4] relative overflow-hidden',
          isActive ? '' : 'hover:bg-[#1E293B]'
        )}
        style={{
          background: isActive ? '#1E293B' : 'transparent',
          borderLeft: `3px solid ${isUnresolved ? sevColor : '#263347'}`,
          outline: isActive ? '1px solid rgba(8,145,178,0.6)' : 'none',
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
              style={{ color: sevColor, flexShrink: 0, opacity: isUnresolved ? 1 : 0.4 }}
            />
            <span
              className="font-semibold truncate"
              style={{ fontSize: 13, color: isUnresolved ? '#E2E8F0' : '#94A3B8', fontFamily: 'Inter, sans-serif' }}
            >
              {incident.device}
            </span>
          </div>
          <span
            className="shrink-0"
            style={{ fontSize: 10, color: '#94A3B8', fontFamily: 'Roboto Mono, monospace' }}
          >
            {timeStr}
            <br />
            {dateStr}
          </span>
        </div>

        <div
          className="mt-0.5 leading-snug"
          style={{ fontSize: 12, color: isUnresolved ? '#E2E8F0' : '#94A3B8', fontFamily: 'Roboto Mono, monospace' }}
        >
          {incident.alarm}
        </div>

        <div className="flex items-center gap-2 mt-1">
          <span
            className="rounded px-1.5 py-0.5 font-medium uppercase tracking-wide"
            style={{
              fontSize: 10,
              background: `${sevColor}18`,
              color: sevColor,
              fontFamily: 'Roboto Mono, monospace',
            }}
          >
            {incident.severity}
          </span>
          <span
            style={{
              fontSize: 10,
              color: isUnresolved ? sevColor : '#94A3B8',
              fontFamily: 'Roboto Mono, monospace',
            }}
          >
            {STATUS_LABEL[incident.status] ?? incident.status}
          </span>
        </div>

        {conversation.agentState === 'waiting_hitl' && (
          <div
            className="mt-1 font-bold animate-pulse"
            style={{ fontSize: 10, color: '#F59E0B', fontFamily: 'Roboto Mono, monospace' }}
          >
            ⏳ AWAITING APPROVAL
          </div>
        )}
      </button>
      {onDelete && (
        <button
          aria-label={`Xoá cảnh báo đã xử lý ${incident.device}`}
          title="Xoá cảnh báo đã xử lý"
          onClick={onDelete}
          className="absolute right-1.5 bottom-2 p-1 rounded opacity-0 group-hover:opacity-100 focus-visible:opacity-100 transition hover:bg-[#334155] focus-visible:outline-2 focus-visible:outline-[#06B6D4]"
          style={{ color: '#94A3B8' }}
        >
          <Trash2Icon size={12} />
        </button>
      )}
    </div>
  )
}

function QACardComp({
  conversation,
  isActive,
  onClick,
  onDelete,
}: {
  conversation: Conversation
  isActive: boolean
  onClick: () => void
  onDelete?: () => void
}) {
  const ts = new Date(conversation.timestamp)
  const timeStr = ts.toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' })
  const dateStr = ts.toLocaleDateString('vi-VN', { day: '2-digit', month: '2-digit' })

  return (
    <div className="group relative" style={{ marginBottom: 2 }}>
      <button
        id={`qa-card-${conversation.id}`}
        aria-label={`Q&A: ${conversation.title}`}
        aria-pressed={isActive}
        onClick={onClick}
        className={cn(
          'w-full text-left px-2.5 py-2 rounded-lg transition border focus-visible:outline-2 focus-visible:outline-[#06B6D4]',
          isActive ? '' : 'hover:bg-[#1E293B99]'
        )}
        style={{
          background: isActive ? '#1E293B' : 'transparent',
          borderColor: isActive ? 'rgba(8,145,178,0.6)' : 'transparent',
        }}
      >
        <div className="flex items-center gap-1.5 min-w-0 pr-5">
          <MessageSquareIcon size={11} style={{ color: '#818CF8', flexShrink: 0 }} />
          <span className="font-medium truncate" style={{ fontSize: 12, color: isActive ? '#FFFFFF' : '#CBD5E1' }}>
            {conversation.title}
          </span>
        </div>
        <div style={{ fontSize: 10, color: '#64748B', marginTop: 2 }}>
          {timeStr} · {dateStr}
        </div>
      </button>
      {onDelete && (
        <button
          aria-label={`Xoá cuộc trò chuyện ${conversation.title}`}
          title="Xoá cuộc trò chuyện"
          onClick={onDelete}
          className="absolute right-1.5 top-1.5 p-1 rounded opacity-0 group-hover:opacity-100 focus-visible:opacity-100 transition hover:bg-[#334155] focus-visible:outline-2 focus-visible:outline-[#06B6D4]"
          style={{ color: '#94A3B8' }}
        >
          <Trash2Icon size={12} />
        </button>
      )}
    </div>
  )
}

function SectionTitle({
  icon, label, count, color, tint, action,
}: { icon: string; label: string; count: number; color: string; tint: string; action?: React.ReactNode }) {
  return (
    <div className="px-2 mb-1 mt-1 flex items-center justify-between gap-2 font-bold uppercase tracking-wider" style={{ fontSize: 11, color }}>
      <span className="truncate">{icon} {label}</span>
      <span className="flex items-center gap-1.5 shrink-0">
        {action}
        <span className="px-1.5 rounded-full" style={{ background: tint }}>{count}</span>
      </span>
    </div>
  )
}

const Empty = ({ text }: { text: string }) => (
  <div className="italic px-2 pb-1" style={{ fontSize: 11, color: '#475569' }}>{text}</div>
)

export default function IncidentSidebar() {
  const {
    sidebarFilter, setSidebarFilter, incidents, conversations, activeConversationId, setActiveConversationId,
    startNewConversation, deleteConversation, dismissAlerts,
  } = useAgenticStore()
  const handled = incidents.filter(isHandled)

  const alerts = conversations.filter((c) => c.type === 'incident')
  const chats = conversations.filter((c) => c.type === 'manual')
  const showAlerts = sidebarFilter !== 'qa'
  const showChats = sidebarFilter !== 'alerts'

  // History grouped by day, newest first, as in other AI chat apps.
  const groups: { label: string; items: Conversation[] }[] = []
  for (const conv of chats) {
    const label = historyGroup(conv.timestamp)
    const last = groups[groups.length - 1]
    if (last?.label === label) last.items.push(conv)
    else groups.push({ label, items: [conv] })
  }

  return (
    <aside
      id="agentic-sidebar"
      className="flex flex-col shrink-0 overflow-hidden"
      style={{
        width: '25%',
        minWidth: 280,
        maxWidth: 340,
        background: 'rgba(2,6,23,0.6)',
        borderRight: '1px solid #1E293B',
      }}
    >
      {/* New conversation + filter tabs */}
      <div className="p-3 shrink-0 space-y-2">
        <button
          id="new-conversation-button"
          onClick={startNewConversation}
          className="w-full flex items-center justify-center gap-2 rounded-xl py-2 transition hover:bg-[#1E293B99] hover:border-[#64748B] focus-visible:outline-2 focus-visible:outline-[#06B6D4]"
          style={{ fontSize: 14, color: '#E2E8F0', border: '1px solid #334155' }}
        >
          <PlusIcon size={15} />
          Cuộc trò chuyện mới
        </button>

        <div className="flex gap-1">
          {(Object.keys(FILTER_LABELS) as SidebarFilter[]).map((f) => (
            <button
              key={f}
              id={`sidebar-filter-${f}`}
              aria-label={`Filter: ${FILTER_LABELS[f]}`}
              aria-pressed={sidebarFilter === f}
              onClick={() => setSidebarFilter(f)}
              className="flex-1 rounded-md text-center font-medium py-1 px-1 transition-all focus-visible:outline-2 focus-visible:outline-[#06B6D4]"
              style={{
                fontSize: 11,
                background: sidebarFilter === f ? '#0891B2' : 'transparent',
                color: sidebarFilter === f ? '#FFFFFF' : '#94A3B8',
                fontFamily: 'Inter, sans-serif',
                border: `1px solid ${sidebarFilter === f ? '#0891B2' : '#1E293B'}`,
              }}
            >
              {FILTER_LABELS[f]}
            </button>
          ))}
        </div>
      </div>

      {/* Threads */}
      <div className="flex-1 overflow-y-auto scrollbar-thin px-2 pb-4 space-y-4">
        {showAlerts && (
          <div>
            <SectionTitle
              icon="⚠"
              label="System Alert"
              count={alerts.length}
              color="#FBBF24"
              tint="rgba(245,158,11,0.2)"
              action={handled.length > 0 && (
                <button
                  id="clear-handled-alerts"
                  onClick={() => dismissAlerts(handled.map((i) => i.id))}
                  title="Xoá mọi cảnh báo đã xử lý (Resolved / Acknowledged / Closed)"
                  className="flex items-center gap-1 rounded px-1.5 py-0.5 normal-case tracking-normal font-medium transition hover:bg-[#1E293B] focus-visible:outline-2 focus-visible:outline-[#06B6D4]"
                  style={{ fontSize: 10, color: '#94A3B8', border: '1px solid #334155' }}
                >
                  <Trash2Icon size={10} />
                  Xoá đã xử lý ({handled.length})
                </button>
              )}
            />
            {alerts.length === 0 && <Empty text="Chưa có cảnh báo" />}
            {alerts.map((conv) => {
              const incident = conv.incidentId ? incidents.find((i) => i.id === conv.incidentId) : undefined
              if (!incident) return null
              return (
                <IncidentCardComp
                  key={conv.id}
                  incident={incident}
                  conversation={conv}
                  isActive={conv.id === activeConversationId}
                  onClick={() => setActiveConversationId(conv.id)}
                  onDelete={isHandled(incident) ? () => dismissAlerts([incident.id]) : undefined}
                />
              )
            })}
          </div>
        )}

        {showChats && (
          <div>
            <SectionTitle
              icon="👤"
              label="User chủ động"
              count={chats.filter((c) => !isBlank(c)).length}
              color="#818CF8"
              tint="rgba(99,102,241,0.2)"
            />
            {chats.length === 0 && <Empty text="Chưa có cuộc trò chuyện" />}
            {groups.map((group) => (
              <div key={group.label} className="mb-2">
                <div className="px-2 py-1" style={{ fontSize: 10, color: '#64748B' }}>{group.label}</div>
                {group.items.map((conv) => (
                  <QACardComp
                    key={conv.id}
                    conversation={conv}
                    isActive={conv.id === activeConversationId}
                    onClick={() => setActiveConversationId(conv.id)}
                    onDelete={isBlank(conv) ? undefined : () => deleteConversation(conv.id)}
                  />
                ))}
              </div>
            ))}
          </div>
        )}
      </div>
    </aside>
  )
}
