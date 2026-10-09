// ─── Agent State Machine ──────────────────────────────────────────────────────

export type AgentState =
  | 'idle'
  | 'observing'
  | 'investigating'
  | 'action_proposed'
  | 'waiting_hitl'
  | 'executing'
  | 'acknowledged'
  | 'rejected'
  | 'expired'

// ─── Severity ─────────────────────────────────────────────────────────────────

export type Severity = 'critical' | 'high' | 'medium' | 'low' | 'info'

export type IncidentStatus =
  | 'active'
  | 'awaiting_approval'
  | 'resolved'
  | 'acknowledged'
  | 'closed'

// ─── Telemetry ─────────────────────────────────────────────────────────────────

export interface TelemetryPoint {
  key: string
  label: string
  value: number
  unit: string
  threshold?: number
  isAnomalous: boolean
  trend: 'up' | 'down' | 'stable'
}

export interface TelemetrySnapshot {
  deviceId: string
  deviceName: string
  timestamp: string
  points: TelemetryPoint[]
  predictionHorizonMin?: number
}

// ─── Citations ─────────────────────────────────────────────────────────────────

export interface Citation {
  id: string
  documentId: string
  documentName: string
  pages?: string
  excerpt?: string
}

// ─── Agent Events (timeline trace) ────────────────────────────────────────────

export type AgentEventType =
  | 'anomaly_detected'
  | 'knowledge_retrieved'
  | 'sop_matched'
  | 'correlation'
  | 'action_proposed'
  | 'waiting_approval'
  | 'executing'
  | 'acknowledged'
  | 'rejected'
  | 'expired'
  | 'query_received'
  | 'response_generated'

export interface AgentEvent {
  id: string
  timestamp: string
  type: AgentEventType
  label: string
  detail?: string
  citations?: Citation[]
}

// ─── Proposed Action ──────────────────────────────────────────────────────────

export type ActionType = 'plc_command' | 'inventory' | 'notify' | 'escalate'

export interface ProposedActionItem {
  type: ActionType
  title: string
  description: string
  params: Record<string, string>
}

export interface ProposedAction {
  id: string
  incidentId: string
  titleVi: string
  subtitleVi: string
  diagnosisEn: string
  items: ProposedActionItem[]
  timerSeconds: number
  createdAt: string
}

// ─── Action Execution ─────────────────────────────────────────────────────────

export type ActionExecutionStatus =
  | 'waiting'
  | 'executing'
  | 'success'
  | 'rejected'
  | 'expired'

export interface ActionExecution {
  actionId: string
  status: ActionExecutionStatus
  executedAt?: string
  ackCode?: string
  responseText?: string
  rejectedAt?: string
  expiredAt?: string
}

// ─── Chat / Conversation ──────────────────────────────────────────────────────

export type MessageRole = 'user' | 'assistant' | 'system'

export interface ChatMessage {
  id: string
  role: MessageRole
  content: string
  timestamp: string
  citations?: Citation[]
  isStreaming?: boolean
}

export type ConversationType = 'manual' | 'incident'

export interface Conversation {
  id: string
  type: ConversationType
  title: string
  timestamp: string
  incidentId?: string
  messages: ChatMessage[]
  agentState: AgentState
  agentEvents: AgentEvent[]
}

// ─── Incident ─────────────────────────────────────────────────────────────────

export interface Incident {
  id: string
  conversationId: string
  device: string
  alarm: string
  severity: Severity
  status: IncidentStatus
  timestamp: string
  resolvedAt?: string
  telemetry?: TelemetrySnapshot
  proposedAction?: ProposedAction
  actionExecution?: ActionExecution
  tags?: string[]
}

// ─── Knowledge Document ───────────────────────────────────────────────────────

export type DocumentIndexStatus =
  | 'uploading'
  | 'parsing'
  | 'chunking'
  | 'embedding'
  | 'vectorized'
  | 'error'

export interface KnowledgeDocument {
  id: string
  name: string
  tags: string[]
  sizeBytes: number
  importedAt: string
  indexStatus: DocumentIndexStatus
  extractedText?: string
  fileUrl?: string
  file?: File
  progress?: number
}

// ─── Sidebar Filter ───────────────────────────────────────────────────────────

export type SidebarFilter = 'all' | 'alerts' | 'qa'
