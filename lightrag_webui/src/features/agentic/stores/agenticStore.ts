import { create } from 'zustand'
import { mockDocuments } from '../mock/knowledge'
import { mockIncidents } from '../mock/incidents'
import { mockConversations } from '../mock/conversations'
import type {
  AgentState,
  ActionExecutionStatus,
  Incident,
  Conversation,
  ChatMessage,
  KnowledgeDocument,
  SidebarFilter,
  TelemetryPoint,
} from '../types/agentic'

const DEMO_MODE = import.meta.env.VITE_DEMO_MODE !== 'false'

interface AgenticStore {
  // ── Identity ───────────────────────────────────────────────────────────────
  isDemoMode: boolean

  // ── Sidebar ────────────────────────────────────────────────────────────────
  sidebarFilter: SidebarFilter
  setSidebarFilter: (f: SidebarFilter) => void

  // ── Active conversation ────────────────────────────────────────────────────
  activeConversationId: string | null
  setActiveConversationId: (id: string | null) => void

  // ── Conversations ──────────────────────────────────────────────────────────
  conversations: Conversation[]
  addUserMessage: (conversationId: string, content: string) => void
  addAssistantMessage: (conversationId: string, content: string, citations?: ChatMessage['citations']) => void
  setAgentState: (conversationId: string, state: AgentState) => void

  // ── Incidents ──────────────────────────────────────────────────────────────
  incidents: Incident[]
  activeIncident: Incident | null

  // ── HITL ───────────────────────────────────────────────────────────────────
  actionExecutions: Record<string, { status: ActionExecutionStatus; executedAt?: string; rejectedAt?: string; expiredAt?: string; ackCode?: string; responseText?: string }>
  approveAction: (actionId: string) => void
  rejectAction: (actionId: string) => void
  expireAction: (actionId: string) => void

  // ── Telemetry live ─────────────────────────────────────────────────────────
  liveTelemetry: Record<string, TelemetryPoint[]>
  updateLiveTelemetry: (deviceId: string, points: TelemetryPoint[]) => void

  // ── Knowledge Hub ──────────────────────────────────────────────────────────
  knowledgeDrawerOpen: boolean
  setKnowledgeDrawerOpen: (open: boolean) => void
  documents: KnowledgeDocument[]
  addDocument: (doc: KnowledgeDocument) => void
  updateDocumentStatus: (id: string, status: KnowledgeDocument['indexStatus'], progress?: number) => void
  deleteDocument: (id: string) => void
  previewDocumentId: string | null
  setPreviewDocumentId: (id: string | null) => void
}

export const useAgenticStore = create<AgenticStore>((set, get) => ({
  isDemoMode: DEMO_MODE,

  // ── Sidebar ────────────────────────────────────────────────────────────────
  sidebarFilter: 'all',
  setSidebarFilter: (f) => set({ sidebarFilter: f }),

  // ── Active conversation ────────────────────────────────────────────────────
  activeConversationId: 'CONV-001',
  setActiveConversationId: (id) => {
    set({ activeConversationId: id })
    // Sync activeIncident
    const conv = get().conversations.find((c) => c.id === id)
    if (conv?.incidentId) {
      const inc = get().incidents.find((i) => i.id === conv.incidentId) ?? null
      set({ activeIncident: inc })
    } else {
      set({ activeIncident: null })
    }
  },

  // ── Conversations ──────────────────────────────────────────────────────────
  conversations: mockConversations,
  addUserMessage: (conversationId, content) => {
    const now = new Date().toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
    const msg: ChatMessage = {
      id: `msg-${Date.now()}`,
      role: 'user',
      content,
      timestamp: now,
    }
    set((s) => ({
      conversations: s.conversations.map((c) =>
        c.id === conversationId ? { ...c, messages: [...c.messages, msg] } : c
      ),
    }))
  },
  addAssistantMessage: (conversationId, content, citations) => {
    const now = new Date().toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
    const msg: ChatMessage = {
      id: `msg-${Date.now()}`,
      role: 'assistant',
      content,
      timestamp: now,
      citations,
    }
    set((s) => ({
      conversations: s.conversations.map((c) =>
        c.id === conversationId ? { ...c, messages: [...c.messages, msg] } : c
      ),
    }))
  },
  setAgentState: (conversationId, state) => {
    set((s) => ({
      conversations: s.conversations.map((c) =>
        c.id === conversationId ? { ...c, agentState: state } : c
      ),
    }))
  },

  // ── Incidents ──────────────────────────────────────────────────────────────
  incidents: mockIncidents,
  activeIncident: mockIncidents.find((i) => i.id === 'INC-001') ?? null,

  // ── HITL ───────────────────────────────────────────────────────────────────
  actionExecutions: {
    'ACT-001': { status: 'waiting' },
  },
  approveAction: (actionId) => {
    set((s) => ({
      actionExecutions: {
        ...s.actionExecutions,
        [actionId]: { status: 'executing' },
      },
    }))
    // Simulate execution delay
    setTimeout(() => {
      set((s) => ({
        actionExecutions: {
          ...s.actionExecutions,
          [actionId]: {
            status: 'success',
            executedAt: new Date().toLocaleTimeString('vi-VN', {
              hour: '2-digit', minute: '2-digit', second: '2-digit'
            }),
            ackCode: 'ACK 200',
            responseText: 'Spindle override set to 50%. Response: OK',
          },
        },
        // Update incident status
        incidents: s.incidents.map((i) =>
          i.proposedAction?.id === actionId
            ? { ...i, status: 'acknowledged' as const }
            : i
        ),
      }))
      // Update conversation agent state
      const inc = get().incidents.find((i) => i.proposedAction?.id === actionId)
      if (inc) {
        get().setAgentState(inc.conversationId, 'acknowledged')
      }
    }, 2200)
  },
  rejectAction: (actionId) => {
    set((s) => ({
      actionExecutions: {
        ...s.actionExecutions,
        [actionId]: {
          status: 'rejected',
          rejectedAt: new Date().toLocaleTimeString('vi-VN', {
            hour: '2-digit', minute: '2-digit', second: '2-digit'
          }),
        },
      },
      incidents: s.incidents.map((i) =>
        i.proposedAction?.id === actionId ? { ...i, status: 'active' as const } : i
      ),
    }))
    const inc = get().incidents.find((i) => i.proposedAction?.id === actionId)
    if (inc) {
      get().setAgentState(inc.conversationId, 'rejected')
    }
  },
  expireAction: (actionId) => {
    set((s) => ({
      actionExecutions: {
        ...s.actionExecutions,
        [actionId]: {
          status: 'expired',
          expiredAt: new Date().toLocaleTimeString('vi-VN', {
            hour: '2-digit', minute: '2-digit', second: '2-digit'
          }),
        },
      },
    }))
    const inc = get().incidents.find((i) => i.proposedAction?.id === actionId)
    if (inc) {
      get().setAgentState(inc.conversationId, 'expired')
    }
  },

  // ── Telemetry live ─────────────────────────────────────────────────────────
  liveTelemetry: {},
  updateLiveTelemetry: (deviceId, points) => {
    set((s) => ({ liveTelemetry: { ...s.liveTelemetry, [deviceId]: points } }))
  },

  // ── Knowledge Hub ──────────────────────────────────────────────────────────
  knowledgeDrawerOpen: false,
  setKnowledgeDrawerOpen: (open) => set({ knowledgeDrawerOpen: open }),
  documents: mockDocuments,
  addDocument: (doc) => set((s) => ({ documents: [doc, ...s.documents] })),
  updateDocumentStatus: (id, status, progress) => {
    set((s) => ({
      documents: s.documents.map((d) =>
        d.id === id ? { ...d, indexStatus: status, progress: progress ?? d.progress } : d
      ),
    }))
  },
  deleteDocument: (id) => {
    set((s) => ({ documents: s.documents.filter((d) => d.id !== id) }))
  },
  previewDocumentId: null,
  setPreviewDocumentId: (id) => set({ previewDocumentId: id }),
}))
