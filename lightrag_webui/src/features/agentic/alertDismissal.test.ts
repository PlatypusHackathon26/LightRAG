import { describe, expect, test } from 'bun:test'
import { DISMISSED_STORAGE_KEY, dismiss, loadDismissed, saveDismissed, visibleIncidents } from './alertDismissal'
import type { Incident } from './types/agentic'

const incident = (id: string, status: Incident['status'], timestamp: string): Incident => ({
  id, conversationId: `CONV-${id}`, device: id, alarm: 'Bất thường', severity: 'medium', status, timestamp,
})

describe('clearing handled alerts', () => {
  test('a resolved alert can be cleared; an active or waiting one cannot', () => {
    const mill = incident('LA-MC-MILL-01', 'resolved', '2026-10-11T17:38:00')
    const robot = incident('LA-MC-ROBOT-01', 'active', '2026-10-11T17:37:00')
    const amr = incident('LA-MC-AMR-01', 'awaiting_approval', '2026-10-11T18:12:00')
    const dismissed = dismiss({}, [mill, robot, amr])
    expect(visibleIncidents([mill, robot, amr], dismissed).map((i) => i.id)).toEqual(['LA-MC-ROBOT-01', 'LA-MC-AMR-01'])
  })

  test('the same machine failing again later shows up again', () => {
    const dismissed = dismiss({}, [incident('LA-MC-MILL-01', 'resolved', '2026-10-11T17:38:00')])
    const again = incident('LA-MC-MILL-01', 'active', '2026-10-11T19:02:00')
    expect(visibleIncidents([again], dismissed).map((i) => i.id)).toEqual(['LA-MC-MILL-01'])
  })

  test('cleared alerts are remembered across reloads; damaged storage clears nothing', () => {
    const data = new Map<string, string>()
    const storage = { getItem: (k: string) => data.get(k) ?? null, setItem: (k: string, v: string) => void data.set(k, v) }
    saveDismissed(storage, { 'LA-MC-MILL-01': '2026-10-11T17:38:00' })
    expect(loadDismissed(storage)).toEqual({ 'LA-MC-MILL-01': '2026-10-11T17:38:00' })
    data.set(DISMISSED_STORAGE_KEY, '[1,2]')
    expect(loadDismissed(storage)).toEqual({})
    expect(loadDismissed({ getItem: () => { throw new Error('blocked') } })).toEqual({})
  })
})
