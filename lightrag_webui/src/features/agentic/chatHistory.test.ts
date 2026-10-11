import { describe, expect, test } from 'bun:test'
import {
  HISTORY_STORAGE_KEY,
  NEW_CONVERSATION_TITLE,
  historyGroup,
  loadHistory,
  newConversation,
  saveHistory,
  titleFrom,
} from './chatHistory'
import type { Conversation } from './types/agentic'

const asked = (id: string, question: string): Conversation => ({
  ...newConversation(new Date(2026, 9, 11, 12)),
  id,
  title: titleFrom(question),
  messages: [{ id: `${id}-m`, role: 'user', content: question, timestamp: '12:00:00', at: '2026-10-11T05:00:00Z' }],
})

const memoryStorage = () => {
  const data = new Map<string, string>()
  return { getItem: (k: string) => data.get(k) ?? null, setItem: (k: string, v: string) => void data.set(k, v), data }
}

describe('chat history', () => {
  test('a conversation is named after its first question, shortened to one line', () => {
    expect(titleFrom('  Cách thay   dao\nmáy CNC? ')).toBe('Cách thay dao máy CNC?')
    const long = titleFrom('x'.repeat(80))
    expect(long.length).toBe(48)
    expect(long.endsWith('…')).toBe(true)
    expect(titleFrom('   ')).toBe(NEW_CONVERSATION_TITLE)
  })

  test('only asked Q&A sessions are saved, and they come back after a reload', () => {
    const storage = memoryStorage()
    const alert: Conversation = { ...asked('CONV-LA-MC-MILL-01', 'x'), type: 'incident' }
    saveHistory(storage, [newConversation(), asked('CONV-Q-1', 'Áp suất tưới nguội tối thiểu?'), alert])
    const back = loadHistory(storage)
    expect(back.map((c) => c.id)).toEqual(['CONV-Q-1'])
    expect(back[0].title).toBe('Áp suất tưới nguội tối thiểu?')
  })

  test('damaged or blocked storage starts without history instead of failing', () => {
    const storage = memoryStorage()
    storage.data.set(HISTORY_STORAGE_KEY, '{not json')
    expect(loadHistory(storage)).toEqual([])
    expect(loadHistory({ getItem: () => { throw new Error('blocked') } })).toEqual([])
    expect(() => saveHistory({ setItem: () => { throw new Error('full') } }, [asked('CONV-Q-1', 'a')])).not.toThrow()
  })

  test('history is grouped by day like other AI chat apps', () => {
    const now = new Date(2026, 9, 11, 9)
    expect(historyGroup(new Date(2026, 9, 11, 1).toISOString(), now)).toBe('Hôm nay')
    expect(historyGroup(new Date(2026, 9, 10, 23).toISOString(), now)).toBe('Hôm qua')
    expect(historyGroup(new Date(2026, 9, 6).toISOString(), now)).toBe('7 ngày trước')
    expect(historyGroup(new Date(2026, 8, 1).toISOString(), now)).toBe('Cũ hơn')
  })
})
