import { create } from 'zustand'
import { mockDocuments } from '../mock/knowledge'
import { mockIncidents } from '../mock/incidents'
import { mockConversations } from '../mock/conversations'
import { agentConfig } from '../agentConfig'
import {
  approveAction as apiApproveAction,
  rejectAction as apiRejectAction,
  fetchIncidents as apiFetchIncidents,
} from '../../../api/agent'
import type {
  AgentEvent,
  AgentState,
  ActionExecutionStatus,
  Incident,
  Conversation,
  ChatMessage,
  KnowledgeDocument,
  SidebarFilter,
  TelemetryPoint,
} from '../types/agentic'

// Mock incidents, telemetry and actions unless the Agent Gateway is live. VITE_AGENT_LIVE is the one
// switch: VITE_DEMO_MODE only chooses the agentic workspace over the LightRAG UI, and the hosted
// demo sets both to true (agentConfig.ts).
const DEMO_MODE = !agentConfig.live

// Live mode (VITE_AGENT_LIVE=true): start from one empty Q&A session; documents and
// incidents are loaded from the Agent Gateway by loadLiveData() instead of the mocks.
export const LIVE_CONVERSATION_ID = 'CONV-LIVE'
const liveConversation = (): Conversation => ({
  id: LIVE_CONVERSATION_ID,
  type: 'manual',
  title: 'Hỏi đáp tài liệu kỹ thuật DENSO',
  timestamp: new Date().toISOString(),
  messages: [],
  agentState: 'idle',
  agentEvents: [],
})

const clock = (iso?: string): string =>
  (iso ? new Date(iso) : new Date()).toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })

interface AgenticStore {
  // ─── Identity ────────────────────────────────────────────────────────
  isDemoMode: boolean
  /** True when VITE_AGENT_LIVE=true: data comes from the Agent Gateway. */
  isLive: boolean
  liveError: string | null
  setLiveError: (message: string | null) => void
  /** Live mode: load documents and incidents from the gateway (no-op with mocks). */
  loadLiveData: (load: { documents: () => Promise<KnowledgeDocument[]>; incidents: () => Promise<Incident[]> }) => Promise<void>

  // ─── Sidebar ─────────────────────────────────────────────────────────
  sidebarFilter: SidebarFilter
  setSidebarFilter: (f: SidebarFilter) => void

  // ─── Active conversation ─────────────────────────────────────────────
  activeConversationId: string | null
  setActiveConversationId: (id: string | null) => void

  // ─── Conversations ───────────────────────────────────────────────────
  conversations: Conversation[]
  addUserMessage: (conversationId: string, content: string) => void
  addAssistantMessage: (conversationId: string, content: string, citations?: ChatMessage['citations']) => void
  setAgentState: (conversationId: string, state: AgentState) => void
  /** Append gateway trace events (ISO timestamps are shown as local clock time). */
  addAgentEvents: (conversationId: string, events: AgentEvent[]) => void

  // ─── Incidents ───────────────────────────────────────────────────────
  incidents: Incident[]
  activeIncident: Incident | null
  fetchRealIncidents: () => Promise<void>

  // ─── HITL ────────────────────────────────────────────────────────────
  actionExecutions: Record<string, { status: ActionExecutionStatus; executedAt?: string; rejectedAt?: string; expiredAt?: string; ackCode?: string; responseText?: string }>
  approveAction: (actionId: string) => void
  rejectAction: (actionId: string) => void
  expireAction: (actionId: string) => void

  // ─── Telemetry live ──────────────────────────────────────────────────
  liveTelemetry: Record<string, TelemetryPoint[]>
  updateLiveTelemetry: (deviceId: string, points: TelemetryPoint[]) => void

  // ─── Knowledge Hub ───────────────────────────────────────────────────
  knowledgeDrawerOpen: boolean
  setKnowledgeDrawerOpen: (open: boolean) => void
  documents: KnowledgeDocument[]
  addDocument: (doc: KnowledgeDocument) => void
  updateDocumentStatus: (id: string, status: KnowledgeDocument['indexStatus'], progress?: number) => void
  updateDocument: (id: string, patch: Partial<KnowledgeDocument>) => void
  /** Live: reload the list from the gateway, keeping rows of uploads still in progress. */
  refreshDocuments: (fetch: () => Promise<KnowledgeDocument[]>) => Promise<void>
  deleteDocument: (id: string) => void
  previewDocumentId: string | null
  setPreviewDocumentId: (id: string | null) => void
}

/** Rows created in the browser for an upload, before the gateway knows the document's id. */
export const UPLOAD_ROW_PREFIX = 'doc-upload-'

export const useAgenticStore = create<AgenticStore>((set, get) => ({
  isDemoMode: DEMO_MODE,
  isLive: agentConfig.live,
  liveError: null,
  setLiveError: (message) => set({ liveError: message }),
  loadLiveData: async (load) => {
    if (!get().isLive) return
    try {
      const [documents, incidents] = await Promise.all([load.documents(), load.incidents()])
      set({ documents, incidents, liveError: null })
    } catch (e) {
      set({ liveError: e instanceof Error ? e.message : String(e) })
    }
  },

  // ─── Sidebar ─────────────────────────────────────────────────────────
  sidebarFilter: 'all',
  setSidebarFilter: (f) => set({ sidebarFilter: f }),

  // ─── Active conversation ─────────────────────────────────────────────
  activeConversationId: agentConfig.live ? LIVE_CONVERSATION_ID : 'CONV-001',
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

  // ─── Conversations ───────────────────────────────────────────────────
  conversations: agentConfig.live ? [liveConversation()] : mockConversations,
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
  addAgentEvents: (conversationId, events) => {
    const shown = events.map((e) => ({ ...e, timestamp: clock(e.timestamp) }))
    set((s) => ({
      conversations: s.conversations.map((c) =>
        c.id === conversationId ? { ...c, agentEvents: [...c.agentEvents, ...shown] } : c
      ),
    }))
  },

  // ─── Incidents ───────────────────────────────────────────────────────
  incidents: DEMO_MODE ? mockIncidents : [],
  activeIncident: DEMO_MODE ? (mockIncidents.find((i) => i.id === 'INC-001') ?? null) : null,

  fetchRealIncidents: async () => {
    if (DEMO_MODE) return
    try {
      const realIncidents = await apiFetchIncidents()
      if (!realIncidents) return

      set((s) => {
        const newConversations = [...s.conversations]
        realIncidents.forEach((inc) => {
          const existingIdx = newConversations.findIndex(
            (c) => c.id === inc.conversationId || c.incidentId === inc.id
          )
          const convTitle = `${inc.device}: ${inc.alarm}`
          const convState: AgentState =
            inc.status === 'awaiting_approval'
              ? 'waiting_hitl'
              : inc.status === 'acknowledged' || inc.status === 'resolved'
                ? 'acknowledged'
                : 'observing'

          const convEvents = inc.timeline || []

          if (existingIdx >= 0) {
            newConversations[existingIdx] = {
              ...newConversations[existingIdx],
              title: convTitle,
              agentState: convState,
              agentEvents: convEvents.length > 0 ? convEvents : newConversations[existingIdx].agentEvents,
            }
          } else {
            const timeStr = new Date(inc.timestamp).toLocaleTimeString('vi-VN', {
              hour: '2-digit',
              minute: '2-digit',
              second: '2-digit',
            })
            newConversations.unshift({
              id: inc.conversationId,
              type: 'incident',
              title: convTitle,
              timestamp: inc.timestamp,
              incidentId: inc.id,
              agentState: convState,
              agentEvents: convEvents,
              messages: [
                {
                  id: `sys-${inc.id}`,
                  role: 'system',
                  content: `🔴 Sự cố tự động kích hoạt: ${inc.alarm}`,
                  timestamp: timeStr,
                },
                {
                  id: `ast-${inc.id}`,
                  role: 'assistant',
                  content: `**${inc.alarm} (${inc.device})**\n\nChẩn đoán: ${
                    inc.proposedAction?.subtitleVi ||
                    inc.proposedAction?.diagnosisEn ||
                    'Hệ thống đang theo dõi và giám sát bệ thử.'
                  }`,
                  timestamp: timeStr,
                },
              ],
            })
          }
        })

        // Sync action executions
        const newActionExecutions = { ...s.actionExecutions }
        realIncidents.forEach((inc) => {
          if (inc.actionExecution) {
            newActionExecutions[inc.actionExecution.actionId] = {
              status: inc.actionExecution.status,
              executedAt: inc.actionExecution.executedAt,
              ackCode: inc.actionExecution.ackCode,
              responseText: inc.actionExecution.responseText,
              rejectedAt: inc.actionExecution.rejectedAt,
              expiredAt: inc.actionExecution.expiredAt,
            }
          } else if (inc.proposedAction && !newActionExecutions[inc.proposedAction.id]) {
            newActionExecutions[inc.proposedAction.id] = { status: 'waiting' }
          }
        })

        let nextActiveInc = s.activeIncident
        let nextActiveConvId = s.activeConversationId

        // The live page opens on the document Q&A session; incidents only fill the sidebar.
        const onLiveQa = s.activeConversationId === LIVE_CONVERSATION_ID
        if (!onLiveQa && (!nextActiveInc || nextActiveInc.id === 'INC-001') && realIncidents.length > 0) {
          nextActiveInc = realIncidents[0]
          nextActiveConvId = realIncidents[0].conversationId
        } else if (nextActiveInc) {
          const updatedActive = realIncidents.find((i) => i.id === nextActiveInc!.id)
          if (updatedActive) nextActiveInc = updatedActive
        }

        return {
          incidents: realIncidents,
          conversations: newConversations,
          actionExecutions: newActionExecutions,
          activeIncident: nextActiveInc,
          activeConversationId: nextActiveConvId,
        }
      })
    } catch {
      // Ignore background network polling errors
    }
  },

  // ─── HITL ────────────────────────────────────────────────────────────
  actionExecutions: (DEMO_MODE ? { 'ACT-001': { status: 'waiting' as const } } : {}) as Record<string, { status: ActionExecutionStatus; executedAt?: string; rejectedAt?: string; expiredAt?: string; ackCode?: string; responseText?: string }>,
  approveAction: (actionId) => {
    if (get().isDemoMode) {
      set((s) => ({
        actionExecutions: {
          ...s.actionExecutions,
          [actionId]: { status: 'executing' },
        },
      }))
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
          incidents: s.incidents.map((i) =>
            i.proposedAction?.id === actionId
              ? { ...i, status: 'acknowledged' as const }
              : i
          ),
        }))
        const inc = get().incidents.find((i) => i.proposedAction?.id === actionId)
        if (inc) {
          get().setAgentState(inc.conversationId, 'acknowledged')
        }
      }, 2200)
    } else {
      set((s) => ({
        actionExecutions: {
          ...s.actionExecutions,
          [actionId]: { status: 'executing' },
        },
      }))
      apiApproveAction(actionId)
        .then((res) => {
          set((s) => ({
            actionExecutions: {
              ...s.actionExecutions,
              [actionId]: {
                status: 'success',
                executedAt: new Date().toLocaleTimeString('vi-VN', {
                  hour: '2-digit', minute: '2-digit', second: '2-digit'
                }),
                ackCode: res.ack,
                responseText: res.ack,
              },
            },
            incidents: s.incidents.map((i) =>
              i.proposedAction?.id === actionId
                ? { ...i, status: 'acknowledged' as const }
                : i
            ),
          }))
          const inc = get().incidents.find((i) => i.proposedAction?.id === actionId)
          if (inc) {
            get().setAgentState(inc.conversationId, 'acknowledged')
          }
          get().fetchRealIncidents()
        })
        .catch((err) => {
          set((s) => ({
            actionExecutions: {
              ...s.actionExecutions,
              [actionId]: {
                status: 'rejected',
                responseText: err.message || 'Lỗi thực thi lệnh',
              },
            },
          }))
        })
    }
  },
  rejectAction: (actionId) => {
    if (get().isDemoMode) {
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
    } else {
      apiRejectAction(actionId)
        .then(() => {
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
          get().fetchRealIncidents()
        })
        .catch(() => {})
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

  // ─── Telemetry live ──────────────────────────────────────────────────
  liveTelemetry: {},
  updateLiveTelemetry: (deviceId, points) => {
    set((s) => ({ liveTelemetry: { ...s.liveTelemetry, [deviceId]: points } }))
  },

  // ─── Knowledge Hub ───────────────────────────────────────────────────
  knowledgeDrawerOpen: false,
  setKnowledgeDrawerOpen: (open) => set({ knowledgeDrawerOpen: open }),
  documents: agentConfig.live ? [] : mockDocuments,
  addDocument: (doc) => set((s) => ({ documents: [doc, ...s.documents] })),
  refreshDocuments: async (fetch) => {
    const fresh = await fetch()
    set((s) => ({
      documents: [
        ...s.documents.filter((d) => d.id.startsWith(UPLOAD_ROW_PREFIX) && d.indexStatus !== 'vectorized' && d.indexStatus !== 'error'),
        ...fresh,
      ],
    }))
  },
  updateDocument: (id, patch) =>
    set((s) => ({ documents: s.documents.map((d) => (d.id === id ? { ...d, ...patch } : d)) })),
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

// Auto-poll real incidents when not in demo mode
if (!DEMO_MODE) {
  useAgenticStore.getState().fetchRealIncidents()
  setInterval(() => {
    useAgenticStore.getState().fetchRealIncidents()
  }, 3500)
}
