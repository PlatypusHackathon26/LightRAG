import { useState, useEffect, useCallback } from 'react'
import { useAgenticStore } from '../stores/agenticStore'
import type { ProposedAction } from '../types/agentic'
import {
  ShieldAlertIcon,
  CpuIcon,
  PackageIcon,
  CheckCircle2Icon,
  XCircleIcon,
  ClockIcon,
  AlertTriangleIcon,
  LoaderIcon,
} from 'lucide-react'

const ACTION_TYPE_ICON: Record<string, React.ComponentType<{ size?: number; style?: React.CSSProperties }>> = {
  plc_command: CpuIcon,
  inventory: PackageIcon,
}

function Countdown({
  seconds,
  onExpire,
  disabled,
}: {
  seconds: number
  onExpire: () => void
  disabled: boolean
}) {
  const [remaining, setRemaining] = useState(seconds)

  useEffect(() => {
    if (disabled) return
    if (remaining <= 0) {
      onExpire()
      return
    }
    const id = setInterval(() => {
      setRemaining((r) => {
        if (r <= 1) {
          clearInterval(id)
          return 0
        }
        return r - 1
      })
    }, 1000)
    return () => clearInterval(id)
  }, [disabled, onExpire, remaining])

  const pct = (remaining / seconds) * 100
  const color = remaining > 20 ? '#10B981' : remaining > 10 ? '#F59E0B' : '#EF4444'

  return (
    <div className="flex flex-col items-center gap-1" aria-label={`Time remaining: ${remaining} seconds`}>
      <div
        className="relative flex items-center justify-center rounded-full"
        style={{ width: 48, height: 48, background: '#0B132B', border: `2px solid ${color}` }}
        role="timer"
        aria-live="polite"
      >
        <svg
          className="absolute inset-0 -rotate-90"
          style={{ width: 48, height: 48 }}
          viewBox="0 0 48 48"
          aria-hidden="true"
        >
          <circle cx="24" cy="24" r="21" fill="none" stroke="#3A506B" strokeWidth="3" />
          <circle
            cx="24"
            cy="24"
            r="21"
            fill="none"
            stroke={color}
            strokeWidth="3"
            strokeDasharray={`${2 * Math.PI * 21}`}
            strokeDashoffset={`${2 * Math.PI * 21 * (1 - pct / 100)}`}
            strokeLinecap="round"
            style={{ transition: 'stroke-dashoffset 1s linear, stroke 0.5s' }}
          />
        </svg>
        <span
          className="text-sm font-bold"
          style={{ color, fontFamily: 'Roboto Mono, monospace', zIndex: 1 }}
        >
          {String(Math.floor(remaining / 60)).padStart(2, '0')}:{String(remaining % 60).padStart(2, '0')}
        </span>
      </div>
      <span className="text-[10px]" style={{ color: '#8a9ab5', fontFamily: 'Roboto Mono, monospace' }}>
        Auto-expire
      </span>
    </div>
  )
}

export default function HITLActionCard({ action }: { action: ProposedAction }) {
  const { actionExecutions, approveAction, rejectAction, expireAction } = useAgenticStore()
  const execution = actionExecutions[action.id] ?? { status: 'waiting' }

  const handleExpire = useCallback(() => {
    if (execution.status === 'waiting') {
      expireAction(action.id)
    }
  }, [action.id, execution.status, expireAction])

  const isWaiting = execution.status === 'waiting'
  const isExecuting = execution.status === 'executing'
  const isSuccess = execution.status === 'success'
  const isRejected = execution.status === 'rejected'
  const isExpired = execution.status === 'expired'
  const isDone = isSuccess || isRejected || isExpired

  return (
    <div
      id="hitl-action-card"
      className="mx-4 my-2 rounded overflow-hidden"
      style={{
        border: `1px solid ${isSuccess ? '#10B981' : isRejected ? '#3A506B' : isExpired ? '#3A506B' : '#F59E0B'}`,
        background: '#0B132B',
        boxShadow: isWaiting || isExecuting ? '0 0 20px #F59E0B20' : 'none',
      }}
      role="region"
      aria-label="Human-in-the-Loop action approval required"
    >
      {/* Header */}
      <div
        className="px-4 py-3 flex items-start justify-between gap-3"
        style={{ background: '#1C2541', borderBottom: '1px solid #3A506B' }}
      >
        <div>
          {/* DEMO badge */}
          <div className="flex items-center gap-2 mb-1">
            <span
              className="text-[10px] font-bold rounded px-1.5 py-0.5 uppercase tracking-wider"
              style={{ background: '#F59E0B20', color: '#F59E0B', border: '1px solid #F59E0B40', fontFamily: 'Roboto Mono, monospace' }}
            >
              ⚠ DEMO ACTION / MOCK PLC
            </span>
          </div>
          <div
            className="text-sm font-bold"
            style={{ color: '#F59E0B', fontFamily: 'Roboto Mono, monospace', letterSpacing: '0.02em' }}
          >
            {action.titleVi}
          </div>
          <div className="text-xs mt-0.5" style={{ color: '#e2e8f0', fontFamily: 'Inter, sans-serif' }}>
            {action.subtitleVi}
          </div>
        </div>
        <ShieldAlertIcon size={24} style={{ color: '#F59E0B', flexShrink: 0 }} />
      </div>

      {/* Body */}
      <div className="px-4 py-3 space-y-3">
        {/* Diagnosis */}
        <div>
          <div className="text-[10px] uppercase tracking-wider mb-1" style={{ color: '#3A506B', fontFamily: 'Roboto Mono, monospace' }}>
            AI Diagnosis
          </div>
          <p className="text-xs leading-relaxed" style={{ color: '#94a3b8', fontFamily: 'Inter, sans-serif' }}>
            {action.diagnosisEn}
          </p>
        </div>

        {/* Proposed action items */}
        <div>
          <div className="text-[10px] uppercase tracking-wider mb-1.5" style={{ color: '#3A506B', fontFamily: 'Roboto Mono, monospace' }}>
            Proposed Actions
          </div>
          <div className="space-y-2">
            {action.items.map((item, idx) => {
              const Icon = ACTION_TYPE_ICON[item.type] ?? AlertTriangleIcon
              return (
                <div
                  key={idx}
                  className="rounded p-2.5"
                  style={{ background: '#1C2541', border: '1px solid #3A506B' }}
                >
                  <div className="flex items-center gap-1.5 mb-2">
                    <div
                      className="rounded flex items-center justify-center"
                      style={{ width: 20, height: 20, background: '#00A89620' }}
                    >
                      <Icon size={11} style={{ color: '#00A896' }} />
                    </div>
                    <span className="text-xs font-semibold" style={{ color: '#00A896', fontFamily: 'Roboto Mono, monospace' }}>
                      {idx + 1}. {item.title}
                    </span>
                    <span className="text-[10px]" style={{ color: '#64748b', fontFamily: 'Roboto Mono, monospace' }}>
                      – {item.description}
                    </span>
                  </div>
                  <div className="grid grid-cols-2 gap-x-4 gap-y-0.5">
                    {Object.entries(item.params).map(([k, v]) => (
                      <div key={k} className="flex items-center gap-1.5">
                        <span className="text-[10px]" style={{ color: '#64748b', fontFamily: 'Roboto Mono, monospace' }}>
                          {k}:
                        </span>
                        <span className="text-[10px] font-bold" style={{ color: '#e2e8f0', fontFamily: 'Roboto Mono, monospace' }}>
                          {v}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )
            })}
          </div>
        </div>

        {/* Safety label */}
        {!isDone && (
          <div
            className="flex items-center justify-center gap-2 rounded py-2"
            style={{ background: '#F59E0B15', border: '1px solid #F59E0B40' }}
            role="status"
          >
            <ShieldAlertIcon size={13} style={{ color: '#F59E0B' }} />
            <span
              className="text-[11px] font-bold uppercase tracking-wider"
              style={{ color: '#F59E0B', fontFamily: 'Roboto Mono, monospace' }}
            >
              Human Approval Required
            </span>
          </div>
        )}

        {/* Action state feedback */}
        {isSuccess && (
          <div
            className="flex items-center gap-3 rounded p-3"
            style={{ background: '#10B98115', border: '1px solid #10B98140' }}
            role="status"
            aria-live="polite"
          >
            <CheckCircle2Icon size={18} style={{ color: '#10B981', flexShrink: 0 }} />
            <div>
              <div className="text-xs font-bold" style={{ color: '#10B981', fontFamily: 'Roboto Mono, monospace' }}>
                ✓ PLC COMMAND ACK
              </div>
              <div className="text-[10px]" style={{ color: '#94a3b8', fontFamily: 'Roboto Mono, monospace' }}>
                {execution.executedAt} &nbsp;|&nbsp; Response: {execution.ackCode}
              </div>
              <div className="text-[10px]" style={{ color: '#94a3b8', fontFamily: 'Roboto Mono, monospace' }}>
                {execution.responseText}
              </div>
              <div
                className="mt-1 text-[10px] rounded px-1.5 py-0.5 inline-block"
                style={{ background: '#10B98120', color: '#10B981', fontFamily: 'Roboto Mono, monospace' }}
              >
                DEMO: No real PLC command was issued
              </div>
            </div>
          </div>
        )}

        {isRejected && (
          <div
            className="flex items-center gap-2 rounded p-2.5"
            style={{ background: '#EF444415', border: '1px solid #EF444440' }}
            role="status"
            aria-live="polite"
          >
            <XCircleIcon size={16} style={{ color: '#EF4444', flexShrink: 0 }} />
            <div>
              <div className="text-xs font-bold" style={{ color: '#EF4444', fontFamily: 'Roboto Mono, monospace' }}>
                Action Rejected
              </div>
              <div className="text-[10px]" style={{ color: '#94a3b8', fontFamily: 'Roboto Mono, monospace' }}>
                {execution.rejectedAt} &nbsp;|&nbsp; Keeping current load
              </div>
            </div>
          </div>
        )}

        {isExpired && (
          <div
            className="flex items-center gap-2 rounded p-2.5"
            style={{ background: '#F59E0B15', border: '1px solid #F59E0B40' }}
            role="status"
            aria-live="polite"
          >
            <ClockIcon size={16} style={{ color: '#F59E0B', flexShrink: 0 }} />
            <div>
              <div className="text-xs font-bold" style={{ color: '#F59E0B', fontFamily: 'Roboto Mono, monospace' }}>
                SAFE STATE SIMULATED
              </div>
              <div className="text-[10px]" style={{ color: '#94a3b8', fontFamily: 'Roboto Mono, monospace' }}>
                No real PLC command was issued. Timer expired at {execution.expiredAt}.
              </div>
            </div>
          </div>
        )}

        {isExecuting && (
          <div
            className="flex items-center gap-2 rounded p-2.5 animate-pulse"
            style={{ background: '#00A89615', border: '1px solid #00A89640' }}
            role="status"
            aria-live="polite"
            aria-label="Executing PLC command"
          >
            <LoaderIcon size={16} className="animate-spin" style={{ color: '#00A896', flexShrink: 0 }} />
            <div className="text-xs font-medium" style={{ color: '#00A896', fontFamily: 'Roboto Mono, monospace' }}>
              EXECUTING (SIMULATED)…
            </div>
          </div>
        )}
      </div>

      {/* Footer: buttons + countdown */}
      {!isDone && !isExecuting && (
        <div
          className="px-4 py-3 flex items-center gap-3"
          style={{ borderTop: '1px solid #3A506B' }}
        >
          <button
            id="hitl-approve-button"
            aria-label="Confirm spindle derate: approve the proposed PLC action"
            onClick={() => approveAction(action.id)}
            disabled={!isWaiting}
            className="flex-1 rounded py-2.5 text-xs font-bold uppercase tracking-wider transition-all focus-visible:outline-2 focus-visible:outline-[#10B981] disabled:opacity-50 disabled:cursor-not-allowed"
            style={{
              background: '#00A896',
              color: '#0B132B',
              fontFamily: 'Roboto Mono, monospace',
              boxShadow: '0 0 12px #00A89640',
            }}
          >
            ✓ CONFIRM SPINDLE DERATE
          </button>

          <button
            id="hitl-reject-button"
            aria-label="Reject the proposed action and keep current spindle load"
            onClick={() => rejectAction(action.id)}
            disabled={!isWaiting}
            className="flex-1 rounded py-2.5 text-xs font-bold uppercase tracking-wider transition-all focus-visible:outline-2 focus-visible:outline-[#EF4444] disabled:opacity-50 disabled:cursor-not-allowed"
            style={{
              background: '#1C2541',
              color: '#EF4444',
              border: '1px solid #EF444440',
              fontFamily: 'Roboto Mono, monospace',
            }}
          >
            ✗ REJECT / KEEP CURRENT
          </button>

          <Countdown
            seconds={action.timerSeconds}
            onExpire={handleExpire}
            disabled={!isWaiting}
          />
        </div>
      )}
    </div>
  )
}
