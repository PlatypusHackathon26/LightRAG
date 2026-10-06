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
      style={{ background: '#FFFFFF', borderBottom: '1px solid #D9E1E8' }}
    >
      <div className="flex items-center gap-1.5 mr-2">
        <div
          className="rounded px-2 py-0.5 font-bold uppercase tracking-wider"
          style={{ fontSize: 10, background: '#EF444418', color: '#EF4444', fontFamily: 'Roboto Mono, monospace' }}
        >
          LIVE
        </div>
        <span className="font-medium" style={{ fontSize: 12, color: '#5B6575', fontFamily: 'Roboto Mono, monospace' }}>
          {telemetry.deviceName}
        </span>
      </div>

      {telemetry.points.map((p) => {
        const TrendIcon = TREND_ICON[p.trend]
        const anomalyColor = p.isAnomalous ? '#EF4444' : '#10B981'
        return (
          <div
            key={p.key}
            className="flex items-center gap-1.5 rounded px-2.5 py-1"
            style={{
              background: p.isAnomalous ? '#FEF2F2' : '#F0F4F8',
              border: `1px solid ${p.isAnomalous ? '#EF444440' : '#D9E1E8'}`,
              boxShadow: p.isAnomalous ? '0 0 8px #EF444415' : 'none',
            }}
          >
            <span style={{ fontSize: 11, color: '#5B6575', fontFamily: 'Roboto Mono, monospace' }}>
              {p.label}:
            </span>
            <span
              className="font-bold"
              style={{ fontSize: 13, color: anomalyColor, fontFamily: 'Roboto Mono, monospace' }}
            >
              {typeof p.value === 'number' && !Number.isInteger(p.value)
                ? p.value.toFixed(1)
                : p.value}
              {p.unit}
            </span>
            <TrendIcon size={11} style={{ color: anomalyColor }} />
          </div>
        )
      })}

      {telemetry.predictionHorizonMin !== undefined && (
        <div className="flex items-center gap-1.5 ml-auto">
          <ClockIcon size={11} style={{ color: '#F59E0B' }} />
          <span className="font-medium" style={{ fontSize: 11, color: '#F59E0B', fontFamily: 'Roboto Mono, monospace' }}>
            Risk horizon: ~{telemetry.predictionHorizonMin} min
          </span>
        </div>
      )}
    </div>
  )
}
