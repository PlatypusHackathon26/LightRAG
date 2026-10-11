/**
 * Live mode: turn the gateway's incidents (Long-agent alerts) into sidebar conversations.
 * Messages that came from the gateway (ids "la-…") are replaced on every refresh; what the
 * operator typed in the thread, and the answers to it, are kept. The thread is in the order
 * things happened, so an alert raised after a question appears below it.
 */
import type { AgentState, ChatMessage, Conversation, Incident, ProposedAction } from './types/agentic'

/** The actions waiting on an incident: all of them from a live gateway, the single one otherwise. */
export const incidentActions = (incident: Incident | undefined): ProposedAction[] =>
  incident?.proposedActions ?? (incident?.proposedAction ? [incident.proposedAction] : [])

export const GATEWAY_MESSAGE_PREFIX = 'la-'

const clock = (iso?: string): string =>
  (iso ? new Date(iso) : new Date()).toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })

const instant = (m: ChatMessage): number => {
  const t = m.at ? Date.parse(m.at) : NaN
  return Number.isNaN(t) ? Number.POSITIVE_INFINITY : t  // undated: keep it at the end
}

function stateFor(incident: Incident): AgentState {
  if (incident.status === 'awaiting_approval') return 'waiting_hitl'
  if (incident.status === 'active') return 'observing'
  return 'idle'
}

/** Conversations after a refresh: one per incident (newest first), then every manual session. */
export function mergeLiveIncidents(conversations: Conversation[], incidents: Incident[]): Conversation[] {
  const byId = new Map(conversations.map((c) => [c.id, c]))
  const incidentConversations = incidents.map((incident): Conversation => {
    const existing = byId.get(incident.conversationId)
    const fromGateway: ChatMessage[] = (incident.messages ?? []).map((m) => ({
      id: m.id,
      role: m.role,
      content: m.content,
      timestamp: clock(m.timestamp),
      at: m.timestamp,
    }))
    const local = (existing?.messages ?? []).filter((m) => !m.id.startsWith(GATEWAY_MESSAGE_PREFIX))
    const busy = existing?.agentState === 'investigating'  // a question in this thread is being answered
    return {
      id: incident.conversationId,
      type: 'incident',
      title: `${incident.device}: ${incident.alarm}`,
      timestamp: incident.timestamp,
      incidentId: incident.id,
      messages: [...fromGateway, ...local].sort((a, b) => instant(a) - instant(b)),  // stable
      agentState: busy ? 'investigating' : stateFor(incident),
      agentEvents: existing?.agentEvents ?? [],
    }
  })
  return [...incidentConversations, ...conversations.filter((c) => c.type !== 'incident')]
}
