import { describe, expect, test } from 'bun:test'
import { actionCommand, firstPage, formatImportedAt } from './format'

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

describe('approve button command', () => {
  test('names the PLC command, in Vietnamese or English params', () => {
    expect(actionCommand([{ type: 'plc_command', params: { 'Lệnh': 'SET_RPM', 'Thiết bị': 'COMP-TB-02' } }])).toBe('SET_RPM')
    expect(actionCommand([
      { type: 'inventory', params: { Action: 'Reserve 1 unit' } },
      { type: 'plc_command', params: { Command: 'S=50' } },
    ])).toBe('S=50')
    expect(actionCommand([{ type: 'inventory', params: {} }])).toBe(undefined)
  })
})
