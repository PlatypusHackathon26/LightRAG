import { useState } from 'react'
import type { AgentEvent } from '../types/agentic'
import {
  ActivityIcon,
  DatabaseIcon,
  FileTextIcon,
  GitMergeIcon,
  ZapIcon,
  ClockIcon,
  CheckCircleIcon,
  XCircleIcon,
  AlertTriangleIcon,
  ChevronDownIcon,
  ChevronUpIcon,
} from 'lucide-react'

const EVENT_ICON: Record<string, React.ComponentType<{ size?: number; style?: React.CSSProperties }>> = {
  anomaly_detected: AlertTriangleIcon,
  knowledge_retrieved: DatabaseIcon,
  sop_matched: FileTextIcon,
  correlation: GitMergeIcon,
  action_proposed: ZapIcon,
  waiting_approval: ClockIcon,
  executing: ActivityIcon,
  acknowledged: CheckCircleIcon,
  rejected: XCircleIcon,
  expired: ClockIcon,
  query_received: ActivityIcon,
  response_generated: CheckCircleIcon,
}

const EVENT_COLOR: Record<string, string> = {
  anomaly_detected: '#EF4444',
  knowledge_retrieved: '#06B6D4',
  sop_matched: '#3B82F6',
  correlation: '#8B5CF6',
  action_proposed: '#F59E0B',
  waiting_approval: '#F59E0B',
  executing: '#06B6D4',
  acknowledged: '#10B981',
  rejected: '#EF4444',
  expired: '#94A3B8',
  query_received: '#06B6D4',
  response_generated: '#10B981',
}

export default function AgentActivityTrace({ events }: { events: AgentEvent[] }) {
  const [expanded, setExpanded] = useState(true)
  const [expandedEvents, setExpandedEvents] = useState<Set<string>>(new Set())

  const toggleEvent = (id: string) => {
    setExpandedEvents((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  if (events.length === 0) return null

  return (
    <div
      className="shrink-0 mx-4 my-2 rounded overflow-hidden"
      style={{ border: '1px solid #334155', background: '#1E293B' }}
    >
      {/* Header */}
      <button
        id="agent-trace-toggle"
        aria-label={expanded ? 'Collapse agent trace' : 'Expand agent trace'}
        aria-expanded={expanded}
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between px-3 py-2 text-left hover:bg-[#1E293B] transition-colors focus-visible:outline-2 focus-visible:outline-[#06B6D4]"
        style={{ borderBottom: expanded ? '1px solid #263347' : 'none' }}
      >
        <div className="flex items-center gap-2">
          <ActivityIcon size={13} style={{ color: '#06B6D4' }} />
          <span className="font-semibold uppercase tracking-wider" style={{ fontSize: 11, color: '#06B6D4', fontFamily: 'Roboto Mono, monospace' }}>
            Agent Execution Trace
          </span>
          <span
            className="rounded px-1.5 py-0.5"
            style={{ fontSize: 10, background: '#083344', color: '#06B6D4', fontFamily: 'Roboto Mono, monospace' }}
          >
            {events.length} events
          </span>
        </div>
        {expanded ? (
          <ChevronUpIcon size={13} style={{ color: '#94A3B8' }} />
        ) : (
          <ChevronDownIcon size={13} style={{ color: '#94A3B8' }} />
        )}
      </button>

      {/* Timeline */}
      {expanded && (
        <div className="px-3 py-2 max-h-48 overflow-y-auto scrollbar-thin">
          <div className="relative">
            {/* Vertical line */}
            <div
              className="absolute left-[17px] top-3 bottom-0"
              style={{ width: 1, background: '#263347' }}
            />
            <div className="space-y-0">
              {events.map((ev, idx) => {
                const Icon = EVENT_ICON[ev.type] ?? ActivityIcon
                const color = EVENT_COLOR[ev.type] ?? '#94A3B8'
                const isExpanded = expandedEvents.has(ev.id)
                const hasDetail = !!ev.detail || (ev.citations && ev.citations.length > 0)
                const isLast = idx === events.length - 1

                return (
                  <div key={ev.id} className="relative flex gap-3">
                    {/* Icon node */}
                    <div className="flex flex-col items-center z-10" style={{ width: 34, flexShrink: 0 }}>
                      <div
                        className="rounded-full flex items-center justify-center"
                        style={{
                          width: 24,
                          height: 24,
                          background: `${color}15`,
                          border: `1px solid ${color}50`,
                          boxShadow: isLast ? `0 0 8px ${color}30` : 'none',
                        }}
                      >
                        <Icon size={12} style={{ color }} />
                      </div>
                      {!isLast && <div style={{ flex: 1, minHeight: 4 }} />}
                    </div>

                    {/* Content */}
                    <div className="flex-1 pb-3 min-w-0">
                      <button
                        aria-label={`Event: ${ev.label}${hasDetail ? ', click to expand' : ''}`}
                        aria-expanded={hasDetail ? isExpanded : undefined}
                        onClick={() => hasDetail && toggleEvent(ev.id)}
                        className={`w-full text-left focus-visible:outline-2 focus-visible:outline-[#06B6D4] rounded ${hasDetail ? 'cursor-pointer' : 'cursor-default'}`}
                        disabled={!hasDetail}
                      >
                        <div className="flex items-center gap-2">
                          <span
                            className="shrink-0"
                            style={{ fontSize: 10, color: '#94A3B8', fontFamily: 'Roboto Mono, monospace' }}
                          >
                            {ev.timestamp}
                          </span>
                          <span
                            className="font-medium"
                            style={{ fontSize: 12, color: '#E2E8F0', fontFamily: 'Inter, sans-serif' }}
                          >
                            {ev.label}
                          </span>
                          {hasDetail && (
                            isExpanded ? (
                              <ChevronUpIcon size={10} style={{ color: '#94A3B8', marginLeft: 'auto', flexShrink: 0 }} />
                            ) : (
                              <ChevronDownIcon size={10} style={{ color: '#94A3B8', marginLeft: 'auto', flexShrink: 0 }} />
                            )
                          )}
                        </div>
                      </button>

                      {isExpanded && hasDetail && (
                        <div
                          className="mt-1 rounded px-2 py-1"
                          style={{ fontSize: 11, background: '#1E293B', color: '#94A3B8', fontFamily: 'Roboto Mono, monospace', lineHeight: 1.5 }}
                        >
                          {ev.detail}
                          {ev.citations && ev.citations.length > 0 && (
                            <div className="mt-1 flex flex-wrap gap-1">
                              {ev.citations.map((c) => (
                                <span
                                  key={c.id}
                                  className="rounded px-1.5 py-0.5"
                                  style={{ fontSize: 10, background: '#083344', color: '#06B6D4', border: '1px solid #06B6D425' }}
                                >
                                  {c.documentName}{c.pages ? ` p.${c.pages}` : ''}
                                </span>
                              ))}
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
