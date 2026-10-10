import { describe, expect, test } from 'bun:test'
import { firstPage, formatImportedAt } from './format'

describe('agentic display helpers', () => {
  test('an ISO timestamp becomes a short local date and time', () => {
    const local = new Date(2026, 9, 8, 22, 4, 5)
    expect(formatImportedAt(local.toISOString())).toEqual({ date: '08/10/2026', time: '22:04' })
  })

  test('an already formatted date is left as it is', () => {
    expect(formatImportedAt('11/10/2026')).toEqual({ date: '11/10/2026' })
    expect(formatImportedAt('2026-13-99Tnonsense')).toEqual({ date: '2026-13-99Tnonsense' })
  })

  test('the first cited page opens the preview', () => {
    expect(firstPage('4')).toBe(4)
    expect(firstPage('29-36')).toBe(29)
    expect(firstPage('4, 7')).toBe(4)
    expect(firstPage(undefined)).toBe(undefined)
    expect(firstPage('')).toBe(undefined)
  })
})
