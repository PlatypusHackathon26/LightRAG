import type { Incident, TelemetrySnapshot } from '../types/agentic'

const ts = (offset: number): string => {
  const d = new Date()
  d.setMinutes(d.getMinutes() - offset)
  return d.toISOString()
}

export const mockTelemetry: Record<string, TelemetrySnapshot> = {
  'INC-001': {
    deviceId: 'CNC-02',
    deviceName: 'CNC Station 02',
    timestamp: ts(3),
    predictionHorizonMin: 25,
    points: [
      { key: 'temp', label: 'Temperature', value: 92, unit: '°C', threshold: 85, isAnomalous: true, trend: 'up' },
      { key: 'vibZ', label: 'Z-axis Vibration', value: 35, unit: '%Δ', threshold: 25, isAnomalous: true, trend: 'up' },
      { key: 'spindleOvrd', label: 'Spindle Override', value: 100, unit: '%', threshold: 100, isAnomalous: false, trend: 'stable' },
      { key: 'coolFlow', label: 'Coolant Flow', value: 7.2, unit: 'L/min', threshold: 3, isAnomalous: false, trend: 'stable' },
    ],
  },
  'INC-002': {
    deviceId: 'CNC-04',
    deviceName: 'CNC Station 04',
    timestamp: ts(45),
    points: [
      { key: 'feedOvrd', label: 'Feed Override', value: 115, unit: '%', threshold: 110, isAnomalous: true, trend: 'up' },
      { key: 'toolWear', label: 'Tool Wear Index', value: 0.78, unit: '', threshold: 0.8, isAnomalous: false, trend: 'up' },
    ],
  },
  'INC-003': {
    deviceId: 'CNC-01',
    deviceName: 'CNC Station 01',
    timestamp: ts(120),
    points: [
      { key: 'temp', label: 'Temperature', value: 74, unit: '°C', threshold: 85, isAnomalous: false, trend: 'down' },
      { key: 'vibZ', label: 'Z-axis Vibration', value: 12, unit: '%Δ', threshold: 25, isAnomalous: false, trend: 'stable' },
    ],
  },
  'INC-004': {
    deviceId: 'CNC-03',
    deviceName: 'CNC Station 03',
    timestamp: ts(280),
    points: [
      { key: 'coolFlow', label: 'Coolant Flow', value: 2.3, unit: 'L/min', threshold: 3, isAnomalous: true, trend: 'down' },
    ],
  },
}

export const mockIncidents: Incident[] = [
  // ── ACTIVE CRITICAL ─────────────────────────────────────────────────────────
  {
    id: 'INC-001',
    conversationId: 'CONV-001',
    device: 'CNC-02',
    alarm: 'Spindle Overheat (92°C)',
    severity: 'critical',
    status: 'awaiting_approval',
    timestamp: ts(3),
    telemetry: mockTelemetry['INC-001'],
    proposedAction: {
      id: 'ACT-001',
      incidentId: 'INC-001',
      titleVi: '⚠ CẢNH BÁO SỰ CỐ CẤP ĐỘ 3',
      subtitleVi: 'Quá nhiệt Spindle Máy CNC-02',
      diagnosisEn:
        'Based on spindle temperature 92°C and Z-axis vibration +35%, the agent estimates a bearing wear scenario and elevated spindle jamming risk. Immediate load reduction is required to prevent unplanned downtime.',
      items: [
        {
          type: 'plc_command',
          title: 'PLC Command',
          description: 'Spindle Override reduction',
          params: {
            'Current value': '100%',
            'Target value': '50%',
            Command: 'S=50',
            Device: 'CNC-02',
          },
        },
        {
          type: 'inventory',
          title: 'Inventory Action',
          description: 'Reserve replacement bearing',
          params: {
            'Part number': '#6205',
            'Warehouse shelf': 'B-04',
            'Stock available': '12 pcs',
            Action: 'Reserve 1 unit',
          },
        },
      ],
      timerSeconds: 60,
      createdAt: ts(2),
    },
    tags: ['#overtemp', '#bearing-risk', '#level-3'],
  },
  // ── ACTIVE HIGH ─────────────────────────────────────────────────────────────
  {
    id: 'INC-002',
    conversationId: 'CONV-002',
    device: 'CNC-04',
    alarm: 'Feed Override > 115%',
    severity: 'high',
    status: 'active',
    timestamp: ts(45),
    telemetry: mockTelemetry['INC-002'],
    tags: ['#feed-override', '#tool-wear'],
  },
  // ── RESOLVED ────────────────────────────────────────────────────────────────
  {
    id: 'INC-003',
    conversationId: 'CONV-003',
    device: 'CNC-01',
    alarm: 'Spindle Overheat (89°C)',
    severity: 'high',
    status: 'resolved',
    timestamp: ts(125),
    resolvedAt: ts(100),
    telemetry: mockTelemetry['INC-003'],
    tags: ['#overtemp', '#resolved'],
  },
  {
    id: 'INC-004',
    conversationId: 'CONV-004',
    device: 'CNC-03',
    alarm: 'Coolant Flow Low (2.3 L/min)',
    severity: 'medium',
    status: 'resolved',
    timestamp: ts(285),
    resolvedAt: ts(250),
    telemetry: mockTelemetry['INC-004'],
    tags: ['#coolant', '#resolved'],
  },
  {
    id: 'INC-005',
    conversationId: 'CONV-005',
    device: 'CNC-02',
    alarm: 'Vibration Spike Z-axis (28%)',
    severity: 'medium',
    status: 'closed',
    timestamp: ts(1440),
    resolvedAt: ts(1400),
    tags: ['#vibration', '#closed'],
  },
]
