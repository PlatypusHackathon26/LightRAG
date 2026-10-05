import type { TelemetrySnapshot } from '../types/agentic'
import { TrendingUpIcon, TrendingDownIcon, MinusIcon, ClockIcon } from 'lucide-react'

const TREND_ICON = {
  up: TrendingUpIcon,
  down: TrendingDownIcon,
  stable: MinusIcon,
}

export default function TelemetryStrip({ telemetry }: { telemetry: TelemetrySnapshot }) {
  return (
    <div
      className="flex items-center gap-3 px-4 py-2 shrink-0 flex-wrap"
      style={{ background: '#0B132B', borderBottom: '1px solid #3A506B' }}
    >
      <div className="flex items-center gap-1.5 mr-2">
        <div
          className="rounded px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider"
          style={{ background: '#EF444420', color: '#EF4444', fontFamily: 'Roboto Mono, monospace' }}
        >
          LIVE
        </div>
        <span className="text-[11px] font-medium" style={{ color: '#8a9ab5', fontFamily: 'Roboto Mono, monospace' }}>
          {telemetry.deviceName}
        </span>
      </div>

      {telemetry.points.map((p) => {
        const TrendIcon = TREND_ICON[p.trend]
        const anomalyColor = p.isAnomalous ? '#EF4444' : '#10B981'
        return (
          <div
            key={p.key}
            className="flex items-center gap-1.5 rounded px-2 py-1"
            style={{
              background: p.isAnomalous ? '#EF444415' : '#1C2541',
              border: `1px solid ${p.isAnomalous ? '#EF444440' : '#3A506B'}`,
              boxShadow: p.isAnomalous ? '0 0 8px #EF444420' : 'none',
            }}
          >
            <span className="text-[10px]" style={{ color: '#8a9ab5', fontFamily: 'Roboto Mono, monospace' }}>
              {p.label}:
            </span>
            <span
              className="text-[11px] font-bold"
              style={{ color: anomalyColor, fontFamily: 'Roboto Mono, monospace' }}
            >
              {typeof p.value === 'number' && !Number.isInteger(p.value)
                ? p.value.toFixed(1)
                : p.value}
              {p.unit}
            </span>
            <TrendIcon size={10} style={{ color: anomalyColor }} />
          </div>
        )
      })}

      {telemetry.predictionHorizonMin !== undefined && (
        <div className="flex items-center gap-1.5 ml-auto">
          <ClockIcon size={11} style={{ color: '#F59E0B' }} />
          <span className="text-[10px] font-medium" style={{ color: '#F59E0B', fontFamily: 'Roboto Mono, monospace' }}>
            Risk horizon: ~{telemetry.predictionHorizonMin} min
          </span>
        </div>
      )}
    </div>
  )
}
