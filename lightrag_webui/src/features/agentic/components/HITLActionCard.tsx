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
        style={{ width: 56, height: 56, background: '#F8FAFC', border: `2px solid ${color}` }}
        role="timer"
        aria-live="polite"
      >
        <svg
          className="absolute inset-0 -rotate-90"
          style={{ width: 56, height: 56 }}
          viewBox="0 0 56 56"
          aria-hidden="true"
        >
          <circle cx="28" cy="28" r="24" fill="none" stroke="#E2E8F0" strokeWidth="3" />
          <circle
            cx="28"
            cy="28"
            r="24"
            fill="none"
            stroke={color}
            strokeWidth="3"
            strokeDasharray={`${2 * Math.PI * 24}`}
            strokeDashoffset={`${2 * Math.PI * 24 * (1 - pct / 100)}`}
            strokeLinecap="round"
            style={{ transition: 'stroke-dashoffset 1s linear, stroke 0.5s' }}
          />
        </svg>
        <span
          className="font-bold"
          style={{ fontSize: 15, color, fontFamily: 'Roboto Mono, monospace', zIndex: 1 }}
        >
          {String(Math.floor(remaining / 60)).padStart(2, '0')}:{String(remaining % 60).padStart(2, '0')}
        </span>
      </div>
      <span style={{ fontSize: 10, color: '#5B6575', fontFamily: 'Roboto Mono, monospace' }}>
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
        border: `2px solid ${isSuccess ? '#10B981' : isRejected ? '#D9E1E8' : isExpired ? '#D9E1E8' : '#F59E0B'}`,
        background: '#FFFFFF',
        boxShadow: isWaiting || isExecuting ? '0 4px 24px rgba(245,158,11,0.15)' : '0 1px 4px rgba(0,0,0,0.06)',
      }}
      role="region"
      aria-label="Human-in-the-Loop action approval required"
    >
      {/* Header */}
      <div
        className="px-4 py-3 flex items-start justify-between gap-3"
        style={{ background: '#FFFBEB', borderBottom: '1px solid #FDE68A' }}
      >
        <div>
          {/* DEMO badge */}
          <div className="flex items-center gap-2 mb-1">
            <span
              className="font-bold rounded px-1.5 py-0.5 uppercase tracking-wider"
              style={{ fontSize: 10, background: '#FEF3C7', color: '#D97706', border: '1px solid #FDE68A', fontFamily: 'Roboto Mono, monospace' }}
            >
              ⚠ DEMO ACTION / MOCK PLC
            </span>
          </div>
          <div
            className="font-bold"
            style={{ fontSize: 15, color: '#92400E', fontFamily: 'Roboto Mono, monospace', letterSpacing: '0.02em' }}
          >
            {action.titleVi}
          </div>
          <div style={{ fontSize: 13, marginTop: 2, color: '#78350F', fontFamily: 'Inter, sans-serif' }}>
            {action.subtitleVi}
          </div>
        </div>
        <ShieldAlertIcon size={26} style={{ color: '#F59E0B', flexShrink: 0 }} />
      </div>

      {/* Body */}
      <div className="px-4 py-3 space-y-3">
        {/* Diagnosis */}
        <div>
          <div className="uppercase tracking-wider mb-1" style={{ fontSize: 10, color: '#5B6575', fontFamily: 'Roboto Mono, monospace' }}>
            AI Diagnosis
          </div>
          <p className="leading-relaxed" style={{ fontSize: 13, color: '#172033', fontFamily: 'Inter, sans-serif' }}>
            {action.diagnosisEn}
          </p>
        </div>

        {/* Proposed action items */}
        <div>
          <div className="uppercase tracking-wider mb-1.5" style={{ fontSize: 10, color: '#5B6575', fontFamily: 'Roboto Mono, monospace' }}>
            Proposed Actions
          </div>
          <div className="space-y-2">
            {action.items.map((item, idx) => {
              const Icon = ACTION_TYPE_ICON[item.type] ?? AlertTriangleIcon
              return (
                <div
                  key={idx}
                  className="rounded p-2.5"
                  style={{ background: '#F8FAFC', border: '1px solid #D9E1E8' }}
                >
                  <div className="flex items-center gap-1.5 mb-2">
                    <div
                      className="rounded flex items-center justify-center"
                      style={{ width: 20, height: 20, background: '#EBF5F4' }}
                    >
                      <Icon size={11} style={{ color: '#00A896' }} />
                    </div>
                    <span className="font-semibold" style={{ fontSize: 13, color: '#00A896', fontFamily: 'Roboto Mono, monospace' }}>
                      {idx + 1}. {item.title}
                    </span>
                    <span style={{ fontSize: 11, color: '#5B6575', fontFamily: 'Roboto Mono, monospace' }}>
                      – {item.description}
                    </span>
                  </div>
                  <div className="grid grid-cols-2 gap-x-4 gap-y-0.5">
                    {Object.entries(item.params).map(([k, v]) => (
                      <div key={k} className="flex items-center gap-1.5">
                        <span style={{ fontSize: 11, color: '#5B6575', fontFamily: 'Roboto Mono, monospace' }}>
                          {k}:
                        </span>
                        <span className="font-bold" style={{ fontSize: 13, color: '#172033', fontFamily: 'Roboto Mono, monospace' }}>
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
            style={{ background: '#FFFBEB', border: '1px solid #FDE68A' }}
            role="status"
          >
            <ShieldAlertIcon size={13} style={{ color: '#F59E0B' }} />
            <span
              className="font-bold uppercase tracking-wider"
              style={{ fontSize: 12, color: '#D97706', fontFamily: 'Roboto Mono, monospace' }}
            >
              Human Approval Required
            </span>
          </div>
        )}

        {/* Action state feedback */}
        {isSuccess && (
          <div
            className="flex items-center gap-3 rounded p-3"
            style={{ background: '#F0FDF4', border: '1px solid #BBF7D0' }}
            role="status"
            aria-live="polite"
          >
            <CheckCircle2Icon size={18} style={{ color: '#10B981', flexShrink: 0 }} />
            <div>
              <div className="font-bold" style={{ fontSize: 13, color: '#065F46', fontFamily: 'Roboto Mono, monospace' }}>
                ✓ PLC COMMAND ACK
              </div>
              <div style={{ fontSize: 11, color: '#5B6575', fontFamily: 'Roboto Mono, monospace' }}>
                {execution.executedAt} &nbsp;|&nbsp; Response: {execution.ackCode}
              </div>
              <div style={{ fontSize: 11, color: '#5B6575', fontFamily: 'Roboto Mono, monospace' }}>
                {execution.responseText}
              </div>
              <div
                className="mt-1 rounded px-1.5 py-0.5 inline-block"
                style={{ fontSize: 10, background: '#DCFCE7', color: '#10B981', fontFamily: 'Roboto Mono, monospace' }}
              >
                DEMO: No real PLC command was issued
              </div>
            </div>
          </div>
        )}

        {isRejected && (
          <div
            className="flex items-center gap-2 rounded p-2.5"
            style={{ background: '#FEF2F2', border: '1px solid #FECACA' }}
            role="status"
            aria-live="polite"
          >
            <XCircleIcon size={16} style={{ color: '#EF4444', flexShrink: 0 }} />
            <div>
              <div className="font-bold" style={{ fontSize: 13, color: '#991B1B', fontFamily: 'Roboto Mono, monospace' }}>
                Action Rejected
              </div>
              <div style={{ fontSize: 11, color: '#5B6575', fontFamily: 'Roboto Mono, monospace' }}>
                {execution.rejectedAt} &nbsp;|&nbsp; Keeping current load
              </div>
            </div>
          </div>
        )}

        {isExpired && (
          <div
            className="flex items-center gap-2 rounded p-2.5"
            style={{ background: '#FFFBEB', border: '1px solid #FDE68A' }}
            role="status"
            aria-live="polite"
          >
            <ClockIcon size={16} style={{ color: '#F59E0B', flexShrink: 0 }} />
            <div>
              <div className="font-bold" style={{ fontSize: 13, color: '#92400E', fontFamily: 'Roboto Mono, monospace' }}>
                SAFE STATE SIMULATED
              </div>
              <div style={{ fontSize: 11, color: '#5B6575', fontFamily: 'Roboto Mono, monospace' }}>
                No real PLC command was issued. Timer expired at {execution.expiredAt}.
              </div>
            </div>
          </div>
        )}

        {isExecuting && (
          <div
            className="flex items-center gap-2 rounded p-2.5 animate-pulse"
            style={{ background: '#EBF5F4', border: '1px solid #00A89640' }}
            role="status"
            aria-live="polite"
            aria-label="Executing PLC command"
          >
            <LoaderIcon size={16} className="animate-spin" style={{ color: '#00A896', flexShrink: 0 }} />
            <div className="font-medium" style={{ fontSize: 13, color: '#00A896', fontFamily: 'Roboto Mono, monospace' }}>
              EXECUTING (SIMULATED)…
            </div>
          </div>
        )}
      </div>

      {/* Footer: buttons + countdown */}
      {!isDone && !isExecuting && (
        <div
          className="px-4 py-3 flex items-center gap-3"
          style={{ borderTop: '1px solid #D9E1E8', background: '#F8FAFC' }}
        >
          <button
            id="hitl-approve-button"
            aria-label="Confirm spindle derate: approve the proposed PLC action"
            onClick={() => approveAction(action.id)}
            disabled={!isWaiting}
            className="flex-1 rounded py-3 font-bold uppercase tracking-wider transition-all focus-visible:outline-2 focus-visible:outline-[#10B981] disabled:opacity-50 disabled:cursor-not-allowed"
            style={{
              fontSize: 13,
              background: '#00A896',
              color: '#FFFFFF',
              fontFamily: 'Roboto Mono, monospace',
              boxShadow: '0 2px 12px rgba(0,168,150,0.35)',
            }}
          >
            ✓ CONFIRM SPINDLE DERATE
          </button>

          <button
            id="hitl-reject-button"
            aria-label="Reject the proposed action and keep current spindle load"
            onClick={() => rejectAction(action.id)}
            disabled={!isWaiting}
            className="flex-1 rounded py-3 font-bold uppercase tracking-wider transition-all focus-visible:outline-2 focus-visible:outline-[#EF4444] disabled:opacity-50 disabled:cursor-not-allowed"
            style={{
              fontSize: 13,
              background: '#FEF2F2',
              color: '#EF4444',
              border: '1px solid #FECACA',
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
