/**
 * Agent Gateway API adapter.
 *
 * Mock mode (default): every call resolves from the local mock data.
 * Live mode (VITE_AGENT_LIVE=true, see features/agentic/agentConfig.ts): calls the
 * DENSO Agent Gateway (denso/gateway/app.py), which fronts the LightRAG servers.
 *
 * Agent Gateway endpoints:
 *   GET  /agent/incidents
 *   GET  /agent/incidents/{id}
 *   POST /agent/chat
 *   GET  /agent/documents
 *   POST /agent/actions/{id}/approve
 *   POST /agent/actions/{id}/reject
 *   GET  /agent/telemetry/{deviceId}
 */

import type {
  AgentEvent,
  Citation,
  Incident,
  KnowledgeDocument,
  TelemetrySnapshot,
} from '../features/agentic/types/agentic'
import { mockIncidents, mockTelemetry } from '../features/agentic/mock/incidents'
import { mockDocuments } from '../features/agentic/mock/knowledge'
import { agentConfig, type AgentConfig } from '../features/agentic/agentConfig'

export interface AgentChatRequest {
  conversationId: string
  message: string
}

export interface AgentChatResponse {
  content: string
  citations?: Citation[]
  /** Live only: retrieval / generation trace for AgentActivityTrace. */
  events?: AgentEvent[]
  /** Live only: which LightRAG tier answered ("knowledge" | "lookup"). */
  target?: string
  /** Live only: false when LightRAG answered without the LLM (e.g. nothing retrieved). */
  llmGenerated?: boolean
}

export class AgentApiError extends Error {
  constructor(
    message: string,
    readonly status: number
  ) {
    super(message)
    this.name = 'AgentApiError'
  }
}

type FetchLike = (input: string, init?: RequestInit) => Promise<Response>

/** Build an agent client; tests pass their own config and fetch. */
export function createAgentClient(config: AgentConfig, fetchImpl: FetchLike = (i, init) => fetch(i, init)) {
  const headers = (extra?: Record<string, string>): Record<string, string> => ({
    ...(config.token ? { Authorization: `Bearer ${config.token}` } : {}),
    ...extra,
  })

  async function request<T>(path: string, init?: RequestInit): Promise<T> {
    const res = await fetchImpl(`${config.baseUrl}${path}`, {
      ...init,
      headers: headers(init?.body ? { 'Content-Type': 'application/json' } : undefined),
    })
    if (!res.ok) {
      let detail = ''
      try {
        detail = (await res.json())?.detail ?? ''
      } catch {
        /* non-JSON error body */
      }
      throw new AgentApiError(`${init?.method ?? 'GET'} ${path} failed: ${res.status}${detail ? ` - ${detail}` : ''}`, res.status)
    }
    return res.json() as Promise<T>
  }

  return {
    live: config.live,

    fetchIncidents(): Promise<Incident[]> {
      if (!config.live) return Promise.resolve([...mockIncidents])
      return request<Incident[]>('/agent/incidents')
    },

    async fetchIncident(id: string): Promise<Incident | undefined> {
      if (!config.live) return mockIncidents.find((i: Incident) => i.id === id)
      try {
        return await request<Incident>(`/agent/incidents/${encodeURIComponent(id)}`)
      } catch (e) {
        if (e instanceof AgentApiError && e.status === 404) return undefined
        throw e
      }
    },

    postAgentChat(req: AgentChatRequest): Promise<AgentChatResponse> {
      if (!config.live) {
        // Mock: echo back a canned response (the demo replies live in ChatWorkspace.tsx)
        return Promise.resolve({ content: `[DEMO] Received: "${req.message}"` })
      }
      return request<AgentChatResponse>('/agent/chat', { method: 'POST', body: JSON.stringify(req) })
    },

    fetchDocuments(): Promise<KnowledgeDocument[]> {
      if (!config.live) return Promise.resolve([...mockDocuments])
      return request<KnowledgeDocument[]>('/agent/documents')
    },

    approveAction(actionId: string): Promise<{ ack: string }> {
      if (!config.live) return Promise.resolve({ ack: 'ACK 200' })
      return request<{ ack: string }>(`/agent/actions/${encodeURIComponent(actionId)}/approve`, { method: 'POST' })
    },

    async rejectAction(actionId: string): Promise<void> {
      if (!config.live) return
      await request(`/agent/actions/${encodeURIComponent(actionId)}/reject`, { method: 'POST' })
    },

    async fetchTelemetry(incidentId: string): Promise<TelemetrySnapshot | undefined> {
      if (!config.live) return mockTelemetry[incidentId]
      try {
        return await request<TelemetrySnapshot>(`/agent/telemetry/${encodeURIComponent(incidentId)}`)
      } catch (e) {
        if (e instanceof AgentApiError && e.status === 404) return undefined
        throw e
      }
    },
  }
}

export const agentClient = createAgentClient(agentConfig)

// Named exports kept for existing callers.
export const fetchIncidents = () => agentClient.fetchIncidents()
export const fetchIncident = (id: string) => agentClient.fetchIncident(id)
export const postAgentChat = (req: AgentChatRequest) => agentClient.postAgentChat(req)
export const fetchDocuments = () => agentClient.fetchDocuments()
export const approveAction = (actionId: string) => agentClient.approveAction(actionId)
export const rejectAction = (actionId: string) => agentClient.rejectAction(actionId)
export const fetchTelemetry = (incidentId: string) => agentClient.fetchTelemetry(incidentId)
