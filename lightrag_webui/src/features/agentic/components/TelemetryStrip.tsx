import type { TelemetryPoint, TelemetrySnapshot } from '../types/agentic'
import { formatReading } from '../format'
import { TrendingUpIcon, TrendingDownIcon, MinusIcon, ClockIcon, AlertTriangleIcon } from 'lucide-react'

const TREND_ICON = {
  up: TrendingUpIcon,
  down: TrendingDownIcon,
  stable: MinusIcon,
}

const TREND_LABEL = { up: 'đang tăng', down: 'đang giảm', stable: 'ổn định' }

/** One reading: the label above, the value large, the state as an icon + word, never colour alone. */
function Reading({ point }: { point: TelemetryPoint }) {
  const TrendIcon = TREND_ICON[point.trend]
  const off = point.isAnomalous
  return (
    <div
      className="rounded-lg px-3 py-2 min-w-0"
      style={{
        background: off ? '#2A1215' : '#1E293B',
        border: `1px solid ${off ? 'rgba(239,68,68,0.6)' : '#263347'}`,
      }}
      title={`${point.label}: ${formatReading(point.value)} ${point.unit} (${TREND_LABEL[point.trend]})`}
    >
      <div className="truncate" style={{ fontSize: 11, color: '#94A3B8' }}>
        {point.label}
      </div>
      <div className="flex items-baseline gap-1 mt-0.5">
        <span className="font-semibold tabular-nums" style={{ fontSize: 18, color: '#F1F5F9', fontFamily: 'Roboto Mono, monospace' }}>
          {formatReading(point.value)}
        </span>
        <span style={{ fontSize: 11, color: '#64748B' }}>{point.unit}</span>
        <TrendIcon size={12} className="ml-auto self-center" style={{ color: '#64748B' }} aria-label={TREND_LABEL[point.trend]} />
      </div>
      {off && (
        <div className="flex items-center gap-1 mt-0.5 font-medium" style={{ fontSize: 10, color: '#F87171' }}>
          <AlertTriangleIcon size={10} />
          Vượt ngưỡng
        </div>
      )}
    </div>
  )
}

export default function TelemetryStrip({ telemetry }: { telemetry: TelemetrySnapshot }) {
  const offCount = telemetry.points.filter((p) => p.isAnomalous).length
  return (
    <section
      className="px-6 py-3 shrink-0"
      style={{ background: '#0F172A', borderBottom: '1px solid #1E293B' }}
      aria-label={`Số liệu trực tiếp: ${telemetry.deviceName}`}
    >
      <div className="flex items-center gap-2 mb-2">
        <span
          className="flex items-center gap-1 rounded px-1.5 py-0.5 font-bold uppercase tracking-wider"
          style={{ fontSize: 10, background: 'rgba(239,68,68,0.15)', color: '#F87171' }}
        >
          <span className="rounded-full animate-pulse" style={{ width: 6, height: 6, background: '#EF4444' }} />
          Live
        </span>
        <span className="font-medium" style={{ fontSize: 12, color: '#CBD5E1' }}>
          {telemetry.deviceName}
        </span>
        <span style={{ fontSize: 11, color: offCount ? '#F87171' : '#64748B' }}>
          · {offCount ? `${offCount} chỉ số vượt ngưỡng` : 'các chỉ số trong ngưỡng'}
        </span>
        {telemetry.predictionHorizonMin !== undefined && (
          <span className="flex items-center gap-1 ml-auto font-medium" style={{ fontSize: 11, color: '#FBBF24' }}>
            <ClockIcon size={11} />
            Rủi ro trong ~{telemetry.predictionHorizonMin} phút
          </span>
        )}
      </div>

      <div className="grid gap-2" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))' }}>
        {telemetry.points.map((p) => (
          <Reading key={p.key} point={p} />
        ))}
      </div>
    </section>
  )
}
