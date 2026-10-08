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
 *   POST /agent/documents              (multipart: file, level) -> upload job
 *   GET  /agent/documents/jobs/{id}    pipeline progress of an upload
 *   DELETE /agent/documents/{id}       remove a document from the knowledge base
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

/** An upload going through the DENSO pipeline (denso/gateway/jobs.py). */
export interface UploadJob {
  id: string
  name: string
  level: number
  status: KnowledgeDocument['indexStatus']
  progress: number
  /** Human-readable current step, e.g. "Docling đang đọc bố cục, bảng và trang". */
  stage: string
  /** Second pass that reads text inside images: pending | running | done | skipped | error. */
  images: string
  error: string | null
  elapsedSeconds: number
}

/** True while the job still has work to do (the image pass runs after the document is searchable). */
export const uploadJobActive = (job: UploadJob) =>
  job.status !== 'error' && (job.status !== 'vectorized' || job.images === 'running' || job.images === 'pending')

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
      // JSON bodies only: a FormData upload must let the browser set its multipart boundary.
      headers: headers(typeof init?.body === 'string' ? { 'Content-Type': 'application/json' } : undefined),
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

    /** Live only: send a raw file through the DENSO pipeline (needs an upload-enabled token). */
    async uploadDocument(file: File, level = 1): Promise<UploadJob> {
      const form = new FormData()
      form.append('file', file)
      form.append('level', String(level))
      const res = await request<{ jobId: string; job: UploadJob }>('/agent/documents', { method: 'POST', body: form })
      return res.job
    },

    fetchUploadJob(jobId: string): Promise<UploadJob> {
      return request<UploadJob>(`/agent/documents/jobs/${encodeURIComponent(jobId)}`)
    },

    /** Live only: remove the document from every knowledge-base server holding it. */
    async deleteDocument(docId: string): Promise<{ status: string; levels: string[] }> {
      if (!config.live) return { status: 'deleted', levels: [] }
      return request(`/agent/documents/${encodeURIComponent(docId)}`, { method: 'DELETE' })
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
export const uploadDocument = (file: File, level?: number) => agentClient.uploadDocument(file, level)
export const fetchUploadJob = (jobId: string) => agentClient.fetchUploadJob(jobId)
export const deleteKnowledgeDocument = (docId: string) => agentClient.deleteDocument(docId)
export const approveAction = (actionId: string) => agentClient.approveAction(actionId)
export const rejectAction = (actionId: string) => agentClient.rejectAction(actionId)
export const fetchTelemetry = (incidentId: string) => agentClient.fetchTelemetry(incidentId)
