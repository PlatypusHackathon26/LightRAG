import type { Conversation } from '../types/agentic'

const ts = (minOffset: number): string => {
  const d = new Date()
  d.setMinutes(d.getMinutes() - minOffset)
  return d.toISOString()
}

const fmt = (iso: string): string => {
  const d = new Date(iso)
  return d.toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

const t1 = ts(3)
const t2 = ts(2.9)
const t3 = ts(2.8)
const t4 = ts(2.7)
const t5 = ts(2.6)
const t6 = ts(2.5)

export const mockConversations: Conversation[] = [
  // ── CONV-001: Critical incident conversation ──────────────────────────────
  {
    id: 'CONV-001',
    type: 'incident',
    title: 'CNC-02: Spindle Overheat (92°C)',
    timestamp: t1,
    incidentId: 'INC-001',
    agentState: 'waiting_hitl',
    agentEvents: [
      {
        id: 'EVT-001-1',
        timestamp: fmt(t1),
        type: 'anomaly_detected',
        label: 'Telemetry anomaly detected',
        detail: 'CNC-02 spindle temperature crossed 88°C threshold. Z-vibration +35% above baseline.',
      },
      {
        id: 'EVT-001-2',
        timestamp: fmt(t2),
        type: 'knowledge_retrieved',
        label: 'Retrieved 6 relevant knowledge chunks',
        detail: 'Queried knowledge base: SOP_Bao_Tri_CNC_02.pdf, FMEA_Spindle_Assembly_Rev4.pdf, Maintenance_Schedule_Line_A_2026.xlsx',
        citations: [
          { id: 'CIT-001', documentId: 'doc-01', documentName: 'SOP_Bao_Tri_CNC_02.pdf', pages: '14–16' },
          { id: 'CIT-002', documentId: 'doc-02', documentName: 'FMEA_Spindle_Assembly_Rev4.pdf', pages: '8–9' },
        ],
      },
      {
        id: 'EVT-001-3',
        timestamp: fmt(t3),
        type: 'sop_matched',
        label: 'Matched SOP_Bao_Tri_CNC_02.pdf',
        detail: 'Section 14–16 matched. Protocol: spindle derate + bearing inspection + coolant auxiliary activation.',
      },
      {
        id: 'EVT-001-4',
        timestamp: fmt(t4),
        type: 'correlation',
        label: 'Correlated temperature + vibration',
        detail: 'Temperature 92°C + Z-vibration +35% → FMEA Failure Mode: Bearing Wear. RPN 312. Estimated risk horizon 25 min.',
      },
      {
        id: 'EVT-001-5',
        timestamp: fmt(t5),
        type: 'action_proposed',
        label: 'Action proposal generated',
        detail: 'Proposed: Spindle Override 100%→50% via PLC command S=50. Reserve bearing #6205 at shelf B-04.',
      },
      {
        id: 'EVT-001-6',
        timestamp: fmt(t6),
        type: 'waiting_approval',
        label: 'Waiting for operator approval',
        detail: 'HITL gate active. Timer: 60 seconds. Action will expire to SAFE STATE if not confirmed.',
      },
    ],
    messages: [
      {
        id: 'MSG-001-1',
        role: 'system',
        content: '🔴 Incident auto-activated by telemetry anomaly detection',
        timestamp: fmt(t1),
      },
      {
        id: 'MSG-001-2',
        role: 'assistant',
        content: `**CRITICAL ALERT – CNC-02 Spindle Overheat**

Tôi đã phát hiện bất thường nghiêm trọng trên máy CNC-02:

| Tham số | Giá trị hiện tại | Ngưỡng | Trạng thái |
|---|---|---|---|
| Nhiệt độ Spindle | **92°C** | 85°C | 🔴 VƯỢT NGƯỠNG |
| Rung Z-axis | **+35%** | +25% | 🔴 VƯỢT NGƯỠNG |
| Spindle Override | 100% | 100% | ⚠️ TỐI ĐA |
| Coolant Flow | 7.2 L/min | 3 L/min | ✅ BÌNH THƯỜNG |

Dựa trên phân tích FMEA và SOP bảo trì, tôi xác định đây là **tình huống mòn ổ đỡ spindle** với rủi ro kẹt trục cao trong **~25 phút** tới.

Tôi đã soạn thảo đề xuất hành động khẩn cấp bên dưới. **Vui lòng xem xét và phê duyệt.**`,
        timestamp: fmt(t5),
        citations: [
          { id: 'CIT-001', documentId: 'doc-01', documentName: 'SOP_Bao_Tri_CNC_02.pdf', pages: '14–16' },
          { id: 'CIT-002', documentId: 'doc-02', documentName: 'FMEA_Spindle_Assembly_Rev4.pdf', pages: '8–9' },
          { id: 'CIT-003', documentId: 'doc-08', documentName: 'Maintenance_Schedule_Line_A_2026.xlsx', pages: 'Sheet 1' },
        ],
      },
    ],
  },

  // ── CONV-002: Active high severity ───────────────────────────────────────
  {
    id: 'CONV-002',
    type: 'incident',
    title: 'CNC-04: Feed Override > 115%',
    timestamp: ts(45),
    incidentId: 'INC-002',
    agentState: 'investigating',
    agentEvents: [
      {
        id: 'EVT-002-1',
        timestamp: fmt(ts(45)),
        type: 'anomaly_detected',
        label: 'Telemetry anomaly detected',
        detail: 'CNC-04 feed override at 115%, approaching tool-wear threshold.',
      },
      {
        id: 'EVT-002-2',
        timestamp: fmt(ts(44)),
        type: 'knowledge_retrieved',
        label: 'Retrieved 3 relevant knowledge chunks',
        detail: 'Querying FMEA, tool wear references...',
      },
    ],
    messages: [
      {
        id: 'MSG-002-1',
        role: 'system',
        content: '🟡 Incident auto-activated – Feed override anomaly',
        timestamp: fmt(ts(45)),
      },
      {
        id: 'MSG-002-2',
        role: 'assistant',
        content: `**HIGH ALERT – CNC-04 Feed Override Anomaly**

CNC-04 đang chạy ở Feed Override **115%**, vượt qua ngưỡng khuyến nghị 110%.

Chỉ số mòn công cụ (Tool Wear Index): **0.78/1.0** – đang tiệm cận giới hạn thay thế.

Đang phân tích thêm dữ liệu lịch sử để xác định xu hướng và đề xuất hành động.`,
        timestamp: fmt(ts(44)),
      },
    ],
  },

  // ── CONV-003: Resolved incident ──────────────────────────────────────────
  {
    id: 'CONV-003',
    type: 'incident',
    title: 'CNC-01: Spindle Overheat (Resolved)',
    timestamp: ts(125),
    incidentId: 'INC-003',
    agentState: 'acknowledged',
    agentEvents: [
      {
        id: 'EVT-003-1',
        timestamp: fmt(ts(125)),
        type: 'anomaly_detected',
        label: 'Telemetry anomaly detected',
        detail: 'CNC-01 spindle temperature 89°C.',
      },
      {
        id: 'EVT-003-2',
        timestamp: fmt(ts(110)),
        type: 'action_proposed',
        label: 'Action proposal generated',
        detail: 'Spindle derate + coolant inspection recommended.',
      },
      {
        id: 'EVT-003-3',
        timestamp: fmt(ts(105)),
        type: 'acknowledged',
        label: 'Action approved and executed',
        detail: 'PLC ACK received. Spindle override set to 60%. Temperature normalized.',
      },
    ],
    messages: [
      {
        id: 'MSG-003-1',
        role: 'assistant',
        content: '✅ Sự cố CNC-01 đã được giải quyết. Nhiệt độ spindle trở về **74°C** sau khi giảm tải.',
        timestamp: fmt(ts(100)),
      },
    ],
  },

  // ── CONV-004 → CONV-005: Manual technical Q&A ────────────────────────────
  {
    id: 'CONV-006',
    type: 'manual',
    title: 'What is the PM interval for CNC-02?',
    timestamp: ts(60),
    agentState: 'idle',
    agentEvents: [],
    messages: [
      {
        id: 'MSG-006-1',
        role: 'user',
        content: 'What is the preventive maintenance interval for CNC-02 spindle bearings?',
        timestamp: fmt(ts(60)),
      },
      {
        id: 'MSG-006-2',
        role: 'assistant',
        content: `Based on the **Maintenance Schedule Line A 2026**, CNC-02 has a bearing inspection **overdue** as of 2026-10-08.

**Standard intervals (from SOP_Bao_Tri_CNC_02.pdf):**
- Spindle bearing inspection: Every **500 operating hours** or 30 days, whichever comes first
- Coolant system: Every 5 days (concentration check)
- Full PM: Every **1000 hours**

⚠️ CNC-02 is currently **3 days overdue** for its bearing PM — this likely contributed to today's overheating incident.`,
        timestamp: fmt(ts(59)),
        citations: [
          { id: 'CIT-Q1', documentId: 'doc-08', documentName: 'Maintenance_Schedule_Line_A_2026.xlsx', pages: 'Sheet 1' },
          { id: 'CIT-Q2', documentId: 'doc-01', documentName: 'SOP_Bao_Tri_CNC_02.pdf', pages: '22–24' },
        ],
      },
    ],
  },
  {
    id: 'CONV-007',
    type: 'manual',
    title: 'PLC command for spindle override',
    timestamp: ts(180),
    agentState: 'idle',
    agentEvents: [],
    messages: [
      {
        id: 'MSG-007-1',
        role: 'user',
        content: 'What PLC command do I use to reduce spindle override to 50%?',
        timestamp: fmt(ts(180)),
      },
      {
        id: 'MSG-007-2',
        role: 'assistant',
        content: `To set spindle override to **50%** on the DENSO CNC line:

\`\`\`
S=50     ; Set spindle override to 50%
\`\`\`

Or using G-code modal:
\`\`\`gcode
M03 S=50  ; Spindle CW at 50% override
\`\`\`

**Safety note:** Per PLC Parameter Reference, the override range is 0–120%. Below 40% may cause surface finish issues at current feed rates. Consider reducing feed override proportionally.`,
        timestamp: fmt(ts(179)),
        citations: [
          { id: 'CIT-P1', documentId: 'doc-03', documentName: 'PLC_Parameter_Reference_DENSO_2026.pdf', pages: '12–13' },
        ],
      },
    ],
  },
  {
    id: 'CONV-008',
    type: 'manual',
    title: 'Bearing part number for CNC-02',
    timestamp: ts(240),
    agentState: 'idle',
    agentEvents: [],
    messages: [
      {
        id: 'MSG-008-1',
        role: 'user',
        content: 'What bearing part number does CNC-02 spindle use?',
        timestamp: fmt(ts(240)),
      },
      {
        id: 'MSG-008-2',
        role: 'assistant',
        content: `CNC-02 spindle uses **Deep Groove Ball Bearings #6205** as the primary spindle bearing.

From inventory (BOM Q4 2026):
| Part | Number | Shelf | Stock |
|---|---|---|---|
| Bearing Deep Groove | **#6205** | **B-04** | 12 pcs |
| Bearing Deep Groove | #6206 (backup) | B-04 | 8 pcs |

Both are currently in stock. Part #6205 is the correct replacement for CNC-02.`,
        timestamp: fmt(ts(239)),
        citations: [
          { id: 'CIT-B1', documentId: 'doc-06', documentName: 'Inventory_BOM_Q4_2026.csv', pages: 'Row 2' },
          { id: 'CIT-B2', documentId: 'doc-11', documentName: 'Electrical_Wiring_CNC02_v2.pdf', pages: '44' },
        ],
      },
    ],
  },
  {
    id: 'CONV-009',
    type: 'manual',
    title: 'OEE report highlights September',
    timestamp: ts(360),
    agentState: 'idle',
    agentEvents: [],
    messages: [
      {
        id: 'MSG-009-1',
        role: 'user',
        content: 'Summarize the OEE report for Line A in September 2026.',
        timestamp: fmt(ts(360)),
      },
      {
        id: 'MSG-009-2',
        role: 'assistant',
        content: `**Line A OEE Summary – September 2026**

Overall OEE: **78.3%** (Target: 85%) — ⚠️ Below target

| Metric | Value | Target |
|---|---|---|
| Availability | 82.1% | 90% |
| Performance | 91.4% | 95% |
| Quality | 98.7% | 99% |

**Top 3 Loss Causes:**
1. 🔴 Spindle overheating (CNC-01, CNC-02): **34%** of downtime
2. 🟡 Tool change errors: 18% of downtime  
3. 🟡 Setup time: 26% of downtime

The RCA for CNC-01's spindle failure in September shows delayed PM as the primary cause. Implementing AI-based early warning (as active today for CNC-02) is the key corrective action.`,
        timestamp: fmt(ts(359)),
        citations: [
          { id: 'CIT-O1', documentId: 'doc-10', documentName: 'OEE_Report_LineA_Sep2026.pdf', pages: '1–4' },
          { id: 'CIT-O2', documentId: 'doc-09', documentName: 'Root_Cause_Analysis_CNC01_Sep2026.pdf', pages: '12–15' },
        ],
      },
    ],
  },
  {
    id: 'CONV-010',
    type: 'manual',
    title: 'LOTO procedure for CNC maintenance',
    timestamp: ts(480),
    agentState: 'idle',
    agentEvents: [],
    messages: [
      {
        id: 'MSG-010-1',
        role: 'user',
        content: 'What is the LOTO procedure before performing spindle maintenance on CNC-02?',
        timestamp: fmt(ts(480)),
      },
      {
        id: 'MSG-010-2',
        role: 'assistant',
        content: `**Lockout/Tagout (LOTO) Procedure – CNC-02 Spindle Maintenance**

1. **Notify** all affected operators and team leader
2. **Identify** all energy sources:
   - Electrical: Main power CB-02 (Panel A, Row 3)
   - Hydraulic: Hydraulic unit shut-off valve
   - Pneumatic: Air supply ball valve at machine rear
3. **Apply LOTO devices** to all isolation points — use personal padlocks
4. **Verify zero energy state** — press spindle start button to confirm no movement
5. **Perform maintenance** — replace bearing #6205
6. **Remove LOTO devices** — only after sign-off from maintenance engineer
7. **Restart and verify** — run spindle at 30% override for 5 minutes, check temperature

⚠️ **Never skip step 4.** Residual energy in capacitors of Mitsubishi MR-J4-700A drive can persist for up to 5 minutes after power-off.`,
        timestamp: fmt(ts(479)),
        citations: [
          { id: 'CIT-L1', documentId: 'doc-13', documentName: 'Safety_Procedure_LOTO_CNC.pdf', pages: '1–6' },
          { id: 'CIT-L2', documentId: 'doc-17', documentName: 'Supplier_Spec_Mitsubishi_MR-J4.pdf', pages: '88' },
        ],
      },
    ],
  },
]
