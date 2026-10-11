/**
 * Chat history for the Q&A sessions, like other AI chat apps: every "Cuộc trò chuyện mới" is its
 * own conversation, named after its first question, kept in this browser's localStorage.
 * Alert threads are not stored: the gateway rebuilds them from Long-agent on every poll.
 */
import type { Conversation } from './types/agentic'

export const NEW_CONVERSATION_TITLE = 'Cuộc trò chuyện mới'
export const HISTORY_STORAGE_KEY = 'denso-agentic-chat-history'
const MAX_STORED = 50
const TITLE_LENGTH = 48

export const newConversation = (now: Date = new Date()): Conversation => ({
  id: `CONV-Q-${now.getTime()}`,
  type: 'manual',
  title: NEW_CONVERSATION_TITLE,
  timestamp: now.toISOString(),
  messages: [],
  agentState: 'idle',
  agentEvents: [],
})

/** A conversation's name: its first question on one line, shortened. */
export function titleFrom(question: string): string {
  const line = question.replace(/\s+/g, ' ').trim()
  return line.length > TITLE_LENGTH ? `${line.slice(0, TITLE_LENGTH - 1).trimEnd()}…` : line || NEW_CONVERSATION_TITLE
}

export const isBlank = (c: Conversation): boolean => c.type === 'manual' && c.messages.length === 0

/** Q&A sessions worth keeping: asked at least once, newest first, nothing mid-stream. */
export function historyToStore(conversations: Conversation[]): Conversation[] {
  return conversations
    .filter((c) => c.type === 'manual' && c.messages.length > 0)
    .map((c) => ({ ...c, agentState: 'idle' as const, messages: c.messages.filter((m) => !m.isStreaming) }))
    .slice(0, MAX_STORED)
}

export function loadHistory(storage: Pick<Storage, 'getItem'> | undefined): Conversation[] {
  try {
    const raw = storage?.getItem(HISTORY_STORAGE_KEY)
    const parsed: unknown = raw ? JSON.parse(raw) : []
    return Array.isArray(parsed) ? historyToStore(parsed as Conversation[]) : []
  } catch {
    return []  // private window, blocked storage or a damaged entry: start without history
  }
}

export function saveHistory(storage: Pick<Storage, 'setItem'> | undefined, conversations: Conversation[]): void {
  try {
    storage?.setItem(HISTORY_STORAGE_KEY, JSON.stringify(historyToStore(conversations)))
  } catch {
    /* storage full or blocked: the session still works, it is just not remembered */
  }
}

/** Day group shown above history items, as in other AI chat apps. */
export function historyGroup(iso: string, now: Date = new Date()): string {
  const day = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()
  const days = Math.round((day(now) - day(new Date(iso))) / 86_400_000)
  if (days <= 0) return 'Hôm nay'
  if (days === 1) return 'Hôm qua'
  if (days < 7) return '7 ngày trước'
  return 'Cũ hơn'
}
