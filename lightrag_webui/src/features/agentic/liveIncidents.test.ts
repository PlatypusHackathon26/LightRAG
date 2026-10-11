import { describe, expect, test } from 'bun:test'
import { mergeLiveIncidents } from './liveIncidents'
import type { Conversation, Incident } from './types/agentic'

const qa: Conversation = {
  id: 'CONV-LIVE', type: 'manual', title: 'Hỏi đáp', timestamp: '2026-10-11T00:00:00Z',
  messages: [], agentState: 'idle', agentEvents: [],
}

const incident = (status: Incident['status'], messages: Incident['messages']): Incident => ({
  id: 'LA-MC-MILL-01', conversationId: 'CONV-LA-MC-MILL-01', device: 'MC-MILL-01',
  alarm: 'Bất thường: Nhiệt độ trục chính', severity: 'high', status,
  timestamp: '2026-10-11T12:04:03', messages,
})

describe('live incidents in the sidebar', () => {
  test('an alert becomes an Automated Alerts thread before the Q&A session', () => {
    const convs = mergeLiveIncidents([qa], [incident('active', [
      { id: 'la-MC-MILL-01-0', role: 'system', content: '⚠ Spindle_Temp_C=78.2', timestamp: '2026-10-11T12:04:03' },
    ])])
    expect(convs.map((c) => c.id)).toEqual(['CONV-LA-MC-MILL-01', 'CONV-LIVE'])
    expect(convs[0].type).toBe('incident')
    expect(convs[0].incidentId).toBe('LA-MC-MILL-01')
    expect(convs[0].title).toBe('MC-MILL-01: Bất thường: Nhiệt độ trục chính')
    expect(convs[0].agentState).toBe('observing')
    expect(convs[0].messages[0].content).toBe('⚠ Spindle_Temp_C=78.2')
  })

  test('a refresh replaces the gateway messages but keeps what the operator asked', () => {
    let convs = mergeLiveIncidents([qa], [incident('active', [
      { id: 'la-MC-MILL-01-0', role: 'system', content: 'old alert', timestamp: '2026-10-11T12:04:03' },
    ])])
    convs = convs.map((c) => c.id === 'CONV-LA-MC-MILL-01'
      ? { ...c, messages: [...c.messages, { id: 'msg-1', role: 'user' as const, content: 'Cần kiểm tra gì?', timestamp: '12:05:00' }] }
      : c)
    convs = mergeLiveIncidents(convs, [incident('active', [
      { id: 'la-MC-MILL-01-0', role: 'system', content: 'new alert', timestamp: '2026-10-11T12:06:00' },
    ])])
    expect(convs[0].messages.map((m) => m.content)).toEqual(['new alert', 'Cần kiểm tra gì?'])
  })

  test('a thread being answered keeps its state; a cleared alert goes idle; a gone one disappears', () => {
    let convs = mergeLiveIncidents([qa], [incident('active', [])])
    convs = convs.map((c) => (c.type === 'incident' ? { ...c, agentState: 'investigating' as const } : c))
    expect(mergeLiveIncidents(convs, [incident('resolved', [])])[0].agentState).toBe('investigating')
    expect(mergeLiveIncidents([qa], [incident('resolved', [])])[0].agentState).toBe('idle')
    expect(mergeLiveIncidents(convs, []).map((c) => c.id)).toEqual(['CONV-LIVE'])
  })
})
