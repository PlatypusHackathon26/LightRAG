import { useEffect, useRef } from 'react'
import { useAgenticStore } from '../stores/agenticStore'
import ChatMessage from './ChatMessage'
import AgentActivityTrace from './AgentActivityTrace'
import HITLActionCard from './HITLActionCard'
import TelemetryStrip from './TelemetryStrip'
import AgentComposer from './AgentComposer'
import { AlertTriangleIcon } from 'lucide-react'
import { agentClient } from '@/api/agent'
import { isBlank } from '../chatHistory'

/** What a new conversation shows before the first question (the original Long-agent welcome). */
function Welcome() {
  return (
    <div className="h-full flex flex-col items-center justify-center text-center px-6 gap-3" style={{ opacity: 0.9 }}>
      <div style={{ fontSize: 48, lineHeight: 1 }} aria-hidden>🏭</div>
      <h2 className="font-bold" style={{ fontSize: 18, color: '#E2E8F0' }}>DENSO Smart Maintenance Agent</h2>
      <p className="max-w-md" style={{ fontSize: 14, color: '#94A3B8', lineHeight: 1.6 }}>
        Chọn một cuộc trò chuyện bên trái, hỏi trực tiếp Agent về sự cố máy, hoặc chờ hệ thống tạo thread{' '}
        <span style={{ color: '#FBBF24' }}>System Alert</span> khi phát hiện bất thường.
      </p>
    </div>
  )
}

// Simulated agent responses for demo mode
const DEMO_RESPONSES = [
  {
    trigger: /pm|maintenance|interval|schedule/i,
    response: 'Based on the **Maintenance Schedule** and **SOP_Bao_Tri_CNC_02.pdf**, here\'s the current PM status:\n\n- CNC-02 bearing inspection is **overdue by 3 days** (due 2026-10-08)\n- Standard bearing PM interval: every 500 hours or 30 days\n- Coolant flush: every 5 working days\n\nThe overdue PM is likely contributing to the current overheating incident.',
    citations: [
      { id: 'r1', documentId: 'doc-08', documentName: 'Maintenance_Schedule_Line_A_2026.xlsx', pages: 'Sheet 1' },
      { id: 'r2', documentId: 'doc-01', documentName: 'SOP_Bao_Tri_CNC_02.pdf', pages: '22–24' },
    ],
  },
  {
    trigger: /bearing|part|6205/i,
    response: '**Bearing #6205** is confirmed available:\n\n| Part | Shelf | Stock | Status |\n|---|---|---|---|\n| Deep Groove #6205 | **B-04** | **12 pcs** | ✅ Available |\n| Deep Groove #6206 (backup) | B-04 | 8 pcs | ✅ Available |\n\nI have already included a reservation for 1x #6205 in the proposed HITL action.',
    citations: [{ id: 'r3', documentId: 'doc-06', documentName: 'Inventory_BOM_Q4_2026.csv', pages: 'Row 2' }],
  },
  {
    trigger: /plc|command|s=|spindle|override/i,
    response: 'To reduce spindle override to 50% on CNC-02:\n\n```gcode\nS=50  ; Spindle override to 50%\n```\n\nThis is the command included in the pending HITL action. Per **PLC_Parameter_Reference_DENSO_2026.pdf**, the override range is 0–120%. Reducing to 50% will lower thermal output significantly while maintaining workpiece quality above 40%.',
    citations: [{ id: 'r4', documentId: 'doc-03', documentName: 'PLC_Parameter_Reference_DENSO_2026.pdf', pages: '12–13' }],
  },
  {
    trigger: /.*/,
    response: 'I have analyzed your query against the knowledge base. Based on current telemetry (CNC-02 spindle at 92°C, Z-vibration +35%) and matching SOP sections, the situation requires immediate attention.\n\nThe proposed HITL action (spindle derate to 50%) remains pending your approval. Please review and confirm or reject the action above.',
    citations: [
      { id: 'r5', documentId: 'doc-01', documentName: 'SOP_Bao_Tri_CNC_02.pdf', pages: '14–16' },
      { id: 'r6', documentId: 'doc-02', documentName: 'FMEA_Spindle_Assembly_Rev4.pdf', pages: '8–9' },
    ],
  },
]

export default function ChatWorkspace() {
  const {
    activeConversationId,
    conversations,
    incidents,
    isLive,
    liveError,
    addUserMessage,
    addAssistantMessage,
    addAgentEvents,
    setAgentState,
  } = useAgenticStore()

  const messagesEndRef = useRef<HTMLDivElement>(null)

  const conversation = conversations.find((c) => c.id === activeConversationId)

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [conversation?.messages.length])

  const handleSend = (content: string) => {
    if (!activeConversationId) return
    addUserMessage(activeConversationId, content)

    if (isLive) {
      const conversationId = activeConversationId
      setAgentState(conversationId, 'investigating')
      agentClient
        .postAgentChat({ conversationId, message: content })
        .then((res) => {
          addAssistantMessage(conversationId, res.content, res.citations)
          if (res.events?.length) addAgentEvents(conversationId, res.events)
          setAgentState(conversationId, 'idle')
        })
        .catch((e: unknown) => {
          const detail = e instanceof Error ? e.message : String(e)
          addAssistantMessage(conversationId, `⚠️ Agent Gateway báo lỗi: ${detail}`)
          setAgentState(conversationId, 'idle')
        })
      return
    }

    // Simulate agent response after delay
    const lower = content.toLowerCase()
    const matched = DEMO_RESPONSES.find((r) => r.trigger.test(lower)) ?? DEMO_RESPONSES[DEMO_RESPONSES.length - 1]

    setTimeout(() => {
      addAssistantMessage(activeConversationId, matched.response, matched.citations)
    }, 1200)
  }

  if (!conversation) {
    return (
      <div className="flex-1 overflow-hidden" style={{ background: '#0F172A' }}>
        <Welcome />
      </div>
    )
  }

  const incident = conversation.incidentId
    ? incidents.find((i) => i.id === conversation.incidentId)
    : undefined

  return (
    <div className="flex-1 flex flex-col overflow-hidden" style={{ background: '#0F172A' }}>
      {/* Workspace header */}
      <div
        className="px-6 py-3 shrink-0 flex items-center justify-between gap-3"
        style={{ borderBottom: '1px solid #1E293B', background: '#0F172A' }}
      >
        <div className="flex items-center gap-2 min-w-0">
          {incident && (
            <AlertTriangleIcon
              size={14}
              style={{ color: incident.severity === 'critical' ? '#EF4444' : '#F59E0B' }}
            />
          )}
          <span className="font-semibold truncate" style={{ fontSize: 14, color: '#CBD5E1', fontFamily: 'Inter, sans-serif' }}>
            {conversation.title}
          </span>
          {incident && (
            <span
              className="rounded px-1.5 py-0.5 font-bold uppercase"
              style={{
                fontSize: 10,
                background: incident.severity === 'critical' ? '#EF444418' : '#F59E0B18',
                color: incident.severity === 'critical' ? '#EF4444' : '#F59E0B',
                fontFamily: 'Roboto Mono, monospace',
              }}
            >
              {incident.severity}
            </span>
          )}
        </div>

        <div className="flex items-center gap-1.5">
          <div
            className="rounded px-2 py-0.5 font-medium"
            style={{ fontSize: 11, background: '#083344', color: '#06B6D4', border: '1px solid #06B6D430', fontFamily: 'Roboto Mono, monospace' }}
          >
            Agent: {conversation.agentState.replace(/_/g, ' ').toUpperCase()}
          </div>
        </div>
      </div>

      {isLive && liveError && (
        <div className="px-4 py-1.5 shrink-0" style={{ fontSize: 12, background: '#2A1215', color: '#F87171', borderBottom: '1px solid #7F1D1D' }}>
          Agent Gateway: {liveError}
        </div>
      )}

      {/* Telemetry strip */}
      {incident?.telemetry && <TelemetryStrip telemetry={incident.telemetry} />}

      {/* Agent trace */}
      {conversation.agentEvents.length > 0 && (
        <AgentActivityTrace events={conversation.agentEvents} />
      )}

      {/* Messages */}
      <div className="flex-1 overflow-y-auto scrollbar-thin py-2">
        {isBlank(conversation) && <Welcome />}
        {conversation.messages.map((msg) => (
          <ChatMessage key={msg.id} message={msg} />
        ))}

        {/* HITL action card - rendered inline after messages */}
        {incident?.proposedAction && (
          <div className="px-0">
            <HITLActionCard action={incident.proposedAction} />
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Composer */}
      <AgentComposer onSend={handleSend} />
    </div>
  )
}
