/**
 * Agent Gateway API adapter.
 *
 * Phase 1: All calls are routed through the mock service when VITE_DEMO_MODE=true.
 * Phase 2: Replace mock implementations with real fetch/axios calls to the Agent Gateway.
 *
 * Agent Gateway endpoints (for Phase 2):
 *   GET  /agent/incidents
 *   GET  /agent/incidents/{id}
 *   POST /agent/chat
 *   POST /agent/actions/{id}/approve
 *   POST /agent/actions/{id}/reject
 *   GET  /agent/telemetry/{deviceId}
 *
 * LightRAG endpoints (already implemented in /api/lightrag.ts):
 *   GET/POST /documents*
 *   POST     /query
 *   POST     /query/stream
 *   GET      /track_status/{track_id}
 */

import type { Incident, TelemetrySnapshot } from '../features/agentic/types/agentic'
import { mockIncidents, mockTelemetry } from '../features/agentic/mock/incidents'

const IS_DEMO = import.meta.env.VITE_DEMO_MODE !== 'false'

// ─── Incident endpoints ────────────────────────────────────────────────────────

export async function fetchIncidents(): Promise<Incident[]> {
  if (IS_DEMO) return Promise.resolve([...mockIncidents])
  const res = await fetch('/agent/incidents')
  if (!res.ok) throw new Error(`fetchIncidents failed: ${res.status}`)
  return res.json()
}

export async function fetchIncident(id: string): Promise<Incident | undefined> {
  if (IS_DEMO) return Promise.resolve(mockIncidents.find((i: Incident) => i.id === id))
  const res = await fetch(`/agent/incidents/${id}`)
  if (!res.ok) throw new Error(`fetchIncident failed: ${res.status}`)
  return res.json()
}

// ─── Chat endpoint ─────────────────────────────────────────────────────────────

export interface AgentChatRequest {
  conversationId: string
  message: string
}

export interface AgentChatResponse {
  content: string
  citations?: { documentId: string; documentName: string; pages?: string }[]
}

export async function postAgentChat(req: AgentChatRequest): Promise<AgentChatResponse> {
  if (IS_DEMO) {
    // Mock: echo back a canned response (real logic is in ChatWorkspace.tsx)
    return Promise.resolve({
      content: `[DEMO] Received: "${req.message}"`,
    })
  }
  const res = await fetch('/agent/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  })
  if (!res.ok) throw new Error(`postAgentChat failed: ${res.status}`)
  return res.json()
}

// ─── Action approval / rejection ──────────────────────────────────────────────

export async function approveAction(actionId: string): Promise<{ ack: string }> {
  if (IS_DEMO) return Promise.resolve({ ack: 'ACK 200' })
  const res = await fetch(`/agent/actions/${actionId}/approve`, { method: 'POST' })
  if (!res.ok) throw new Error(`approveAction failed: ${res.status}`)
  return res.json()
}

export async function rejectAction(actionId: string): Promise<void> {
  if (IS_DEMO) return Promise.resolve()
  const res = await fetch(`/agent/actions/${actionId}/reject`, { method: 'POST' })
  if (!res.ok) throw new Error(`rejectAction failed: ${res.status}`)
}

// ─── Telemetry ─────────────────────────────────────────────────────────────────

export async function fetchTelemetry(incidentId: string): Promise<TelemetrySnapshot | undefined> {
  if (IS_DEMO) return Promise.resolve(mockTelemetry[incidentId])
  const res = await fetch(`/agent/telemetry/${incidentId}`)
  if (!res.ok) throw new Error(`fetchTelemetry failed: ${res.status}`)
  return res.json()
}
