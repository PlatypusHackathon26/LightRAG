import { afterEach, describe, expect, test } from 'bun:test'
import { cleanup, screen } from '@testing-library/react'

import { renderWithProviders } from '@/test/render'
import type { ProposedAction } from '../types/agentic'
import HITLActionCard from './HITLActionCard'

/**
 * The approve button names the command the operator is approving. It used to read
 * "CONFIRM SPINDLE DERATE" (the CNC demo) whatever the proposed command was.
 */
const action = (params: Record<string, string>): ProposedAction => ({
  id: 'ACT-TEST',
  incidentId: 'INC-TEST',
  titleVi: 'Đề xuất: SET_RPM',
  subtitleVi: 'Hạ tốc độ máy nén',
  diagnosisEn: 'Condenser fan failure',
  items: [{ type: 'plc_command', title: 'Lệnh điều khiển PLC', description: 'SET_RPM', params }],
  timerSeconds: 60,
  createdAt: '2026-10-11T00:00:00Z',
})

afterEach(cleanup)

describe('HITL approve button', () => {
  test('names the proposed command', () => {
    renderWithProviders(<HITLActionCard action={action({ 'Lệnh': 'SET_RPM', 'Thiết bị': 'COMP-TB-02' })} />)
    const approve = screen.getByRole('button', { name: 'Approve the proposed command SET_RPM' })
    expect(approve.textContent).toBe('✓ DUYỆT LỆNH SET_RPM')
    expect(screen.queryAllByText(/SPINDLE/i).length).toBe(0)
    expect(screen.getByRole('button', { name: /^Reject/ }).textContent).toBe('✗ TỪ CHỐI / GIỮ NGUYÊN')
  })

  test('falls back to a plain label when the action names no command', () => {
    renderWithProviders(<HITLActionCard action={action({ 'Thiết bị': 'COMP-TB-02' })} />)
    expect(screen.getByRole('button', { name: 'Approve the proposed command' }).textContent).toBe('✓ DUYỆT LỆNH')
  })
})
