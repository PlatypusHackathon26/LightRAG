import { create } from 'zustand'
import { mockDocuments } from '../mock/knowledge'
import { mockIncidents } from '../mock/incidents'
import { mockConversations } from '../mock/conversations'
import { agentConfig } from '../agentConfig'
import { incidentActions, mergeLiveIncidents } from '../liveIncidents'
import { NEW_CONVERSATION_TITLE, isBlank, loadHistory, newConversation, saveHistory, titleFrom } from '../chatHistory'
import { type DismissedAlerts, dismiss, loadDismissed, saveDismissed, visibleIncidents } from '../alertDismissal'
import { agentClient } from '../../../api/agent'
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

const DEMO_MODE = import.meta.env.VITE_DEMO_MODE !== 'false'

// Live mode (VITE_AGENT_LIVE=true): open on a new, empty Q&A session above the saved history;
// documents and incidents are loaded from the Agent Gateway by loadLiveData() instead of the mocks.
const browserStorage = (): Storage | undefined => {
  try {
    return typeof window === 'undefined' ? undefined : window.localStorage
  } catch {
    return undefined  // storage blocked: run without history
  }
}
const firstConversation = newConversation()
const SIDEBAR_STORAGE_KEY = 'denso-agentic-sidebar-open'
const initialSidebarOpen = (): boolean => {
  try {
    return browserStorage()?.getItem(SIDEBAR_STORAGE_KEY) !== 'false'
  } catch {
    return true
  }
}
const initialConversations: Conversation[] = agentConfig.live
  ? [firstConversation, ...loadHistory(browserStorage())]
  : mockConversations

const clock = (iso?: string): string =>
  (iso ? new Date(iso) : new Date()).toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })

interface AgenticStore {
  // ── Identity ───────────────────────────────────────────────────────────────
  isDemoMode: boolean
  /** True when VITE_AGENT_LIVE=true: data comes from the Agent Gateway. */
  isLive: boolean
  liveError: string | null
  setLiveError: (message: string | null) => void
  /** Live mode: load documents and incidents from the gateway (no-op with mocks). */
  loadLiveData: (load: { documents: () => Promise<KnowledgeDocument[]>; incidents: () => Promise<Incident[]> }) => Promise<void>
  /** Live mode: replace the incidents and rebuild their sidebar threads (polled by the workspace). */
  syncLiveIncidents: (incidents: Incident[]) => void

  // ── Sidebar ────────────────────────────────────────────────────────────────
  sidebarFilter: SidebarFilter
  setSidebarFilter: (f: SidebarFilter) => void
  /** The left panel can be collapsed, as in Claude; remembered in this browser. */
  sidebarOpen: boolean
  setSidebarOpen: (open: boolean) => void
  /** Alerts the operator cleared (only handled ones), by incident id and episode timestamp. */
  dismissedAlerts: DismissedAlerts
  /** Clear handled alerts from the sidebar; active or waiting ones are kept. */
  dismissAlerts: (incidentIds: string[]) => void

  // ── Active conversation ────────────────────────────────────────────────────
  activeConversationId: string | null
  setActiveConversationId: (id: string | null) => void

  // ── Conversations ──────────────────────────────────────────────────────────
  conversations: Conversation[]
  /** "Cuộc trò chuyện mới": open an empty Q&A session (reuses one that is still empty). */
  startNewConversation: () => void
  /** Remove a Q&A session from the history. */
  deleteConversation: (id: string) => void
  addUserMessage: (conversationId: string, content: string) => void
  addAssistantMessage: (conversationId: string, content: string, citations?: ChatMessage['citations']) => void
  setAgentState: (conversationId: string, state: AgentState) => void
  /** Append gateway trace events (ISO timestamps are shown as local clock time). */
  addAgentEvents: (conversationId: string, events: AgentEvent[]) => void

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
  updateDocument: (id: string, patch: Partial<KnowledgeDocument>) => void
  /** Live: reload the list from the gateway, keeping rows of uploads still in progress. */
  refreshDocuments: (fetch: () => Promise<KnowledgeDocument[]>) => Promise<void>
  deleteDocument: (id: string) => void
  previewDocumentId: string | null
  setPreviewDocumentId: (id: string | null) => void
}

const ownsAction = (incident: Incident, actionId: string): boolean =>
  incidentActions(incident).some((a) => a.id === actionId)

/** Another action of the same incident still waits for a decision (so the incident is not done yet). */
const othersWaiting = (
  incident: Incident,
  actionId: string,
  executions: Record<string, { status: ActionExecutionStatus }>,
): boolean =>
  incidentActions(incident).some((a) => a.id !== actionId && (executions[a.id]?.status ?? 'waiting') === 'waiting')

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
      set({ documents, liveError: null })
      get().syncLiveIncidents(incidents)
    } catch (e) {
      set({ liveError: e instanceof Error ? e.message : String(e) })
    }
  },
  syncLiveIncidents: (incidents) => {
    set((s) => {
      const active = s.conversations.find((c) => c.id === s.activeConversationId)
      incidents = visibleIncidents(incidents, s.dismissedAlerts)
      return {
        incidents,
        conversations: mergeLiveIncidents(s.conversations, incidents),
        activeIncident: active?.incidentId ? (incidents.find((i) => i.id === active.incidentId) ?? null) : s.activeIncident,
      }
    })
  },

  // ── Sidebar ────────────────────────────────────────────────────────────────
  sidebarFilter: 'all',
  setSidebarFilter: (f) => set({ sidebarFilter: f }),
  sidebarOpen: initialSidebarOpen(),
  setSidebarOpen: (open) => {
    set({ sidebarOpen: open })
    try {
      browserStorage()?.setItem(SIDEBAR_STORAGE_KEY, String(open))
    } catch {
      /* not remembered: still works for this visit */
    }
  },
  dismissedAlerts: loadDismissed(browserStorage()),
  dismissAlerts: (incidentIds) => {
    const s = get()
    const dismissedAlerts = dismiss(s.dismissedAlerts, s.incidents.filter((i) => incidentIds.includes(i.id)))
    saveDismissed(browserStorage(), dismissedAlerts)
    const incidents = visibleIncidents(s.incidents, dismissedAlerts)
    const kept = new Set(incidents.map((i) => i.id))
    set({
      dismissedAlerts,
      incidents,
      conversations: s.conversations.filter((c) => c.type !== 'incident' || (c.incidentId !== undefined && kept.has(c.incidentId))),
    })
    if (!get().conversations.some((c) => c.id === get().activeConversationId)) get().startNewConversation()
  },

  // ── Active conversation ────────────────────────────────────────────────────
  activeConversationId: agentConfig.live ? firstConversation.id : 'CONV-001',
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
  conversations: initialConversations,
  startNewConversation: () => {
    const { conversations, activeConversationId, sidebarFilter } = get()
    const blank = conversations.find((c) => c.id === activeConversationId && isBlank(c)) ?? conversations.find(isBlank)
    const conversation = blank ?? newConversation()
    if (!blank) set({ conversations: [conversation, ...conversations] })
    if (sidebarFilter === 'alerts') set({ sidebarFilter: 'all' })
    get().setActiveConversationId(conversation.id)
  },
  deleteConversation: (id) => {
    set((s) => ({ conversations: s.conversations.filter((c) => c.id !== id || c.type !== 'manual') }))
    if (get().activeConversationId === id) get().startNewConversation()
  },
  addUserMessage: (conversationId, content) => {
    const now = new Date().toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
    const msg: ChatMessage = {
      id: `msg-${Date.now()}`,
      role: 'user',
      content,
      timestamp: now,
      at: new Date().toISOString(),
    }
    set((s) => {
      const target = s.conversations.find((c) => c.id === conversationId)
      if (!target) return {}
      // A Q&A session is named after its first question and moves to the top of the history.
      const named = target.type === 'manual' && target.title === NEW_CONVERSATION_TITLE && target.messages.length === 0
      const updated: Conversation = {
        ...target,
        title: named ? titleFrom(content) : target.title,
        timestamp: target.type === 'manual' ? msg.at! : target.timestamp,
        messages: [...target.messages, msg],
      }
      const rest = s.conversations.filter((c) => c.id !== conversationId)
      return { conversations: target.type === 'manual' ? [updated, ...rest] : s.conversations.map((c) => (c.id === conversationId ? updated : c)) }
    })
  },
  addAssistantMessage: (conversationId, content, citations) => {
    const now = new Date().toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
    const msg: ChatMessage = {
      id: `msg-${Date.now()}`,
      role: 'assistant',
      content,
      timestamp: now,
      at: new Date().toISOString(),
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

  // ── Incidents ──────────────────────────────────────────────────────────────
  incidents: agentConfig.live ? [] : mockIncidents,
  activeIncident: agentConfig.live ? null : (mockIncidents.find((i) => i.id === 'INC-001') ?? null),

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
    if (get().isLive) {
      // The gateway passes the decision to Long-agent, which runs the command on its simulator.
      const now = () => new Date().toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
      agentClient.approveAction(actionId).then(
        (res) => {
          set((s) => ({
            actionExecutions: { ...s.actionExecutions, [actionId]: { status: 'success', executedAt: now(), ackCode: res.ack, responseText: res.ack } },
            incidents: s.incidents.map((i) => (ownsAction(i, actionId) && !othersWaiting(i, actionId, s.actionExecutions) ? { ...i, status: 'acknowledged' as const } : i)),
          }))
          const inc = get().incidents.find((i) => ownsAction(i, actionId))
          if (inc && !othersWaiting(inc, actionId, get().actionExecutions)) get().setAgentState(inc.conversationId, 'acknowledged')
        },
        (e: unknown) => {
          // Not executed (no right, expired, Long-agent down): say so, never show it as done.
          set((s) => ({
            actionExecutions: { ...s.actionExecutions, [actionId]: { status: 'rejected', rejectedAt: now(), responseText: e instanceof Error ? e.message : String(e) } },
          }))
        }
      )
      return
    }
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
          ownsAction(i, actionId) && !othersWaiting(i, actionId, s.actionExecutions)
            ? { ...i, status: 'acknowledged' as const }
            : i
        ),
      }))
      // Update conversation agent state
      const inc = get().incidents.find((i) => ownsAction(i, actionId))
      if (inc && !othersWaiting(inc, actionId, get().actionExecutions)) {
        get().setAgentState(inc.conversationId, 'acknowledged')
      }
    }, 2200)
  },
  rejectAction: (actionId) => {
    if (get().isLive) void agentClient.rejectAction(actionId).catch(() => { /* the ticket expires on its own */ })
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
        ownsAction(i, actionId) && !othersWaiting(i, actionId, s.actionExecutions) ? { ...i, status: 'active' as const } : i
      ),
    }))
    const inc = get().incidents.find((i) => ownsAction(i, actionId))
    if (inc && !othersWaiting(inc, actionId, get().actionExecutions)) {
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
    const inc = get().incidents.find((i) => ownsAction(i, actionId))
    if (inc && !othersWaiting(inc, actionId, get().actionExecutions)) {
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

// Live mode: remember the Q&A sessions in this browser (alert threads come back from the gateway).
if (agentConfig.live) {
  useAgenticStore.subscribe((s, prev) => {
    if (s.conversations !== prev.conversations) saveHistory(browserStorage(), s.conversations)
  })
}
