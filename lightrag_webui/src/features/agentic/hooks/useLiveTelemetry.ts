import { useEffect } from 'react'
import { useAgenticStore } from '../stores/agenticStore'
import type { TelemetryPoint } from '../types/agentic'

// Jitter a value by ±maxPct percent of its base
function jitter(base: number, maxPct: number, min?: number, max?: number): number {
  const delta = base * (maxPct / 100) * (Math.random() * 2 - 1)
  let v = base + delta
  if (min !== undefined) v = Math.max(min, v)
  if (max !== undefined) v = Math.min(max, v)
  return Math.round(v * 10) / 10
}

// Base telemetry for each device
const BASE: Record<string, TelemetryPoint[]> = {
  'CNC-02': [
    { key: 'temp', label: 'Temperature', value: 92, unit: '°C', threshold: 85, isAnomalous: true, trend: 'up' },
    { key: 'vibZ', label: 'Z-axis Vibration', value: 35, unit: '%Δ', threshold: 25, isAnomalous: true, trend: 'up' },
    { key: 'spindleOvrd', label: 'Spindle Override', value: 100, unit: '%', threshold: 100, isAnomalous: false, trend: 'stable' },
    { key: 'coolFlow', label: 'Coolant Flow', value: 7.2, unit: 'L/min', threshold: 3, isAnomalous: false, trend: 'stable' },
  ],
}

function tick(base: TelemetryPoint[]): TelemetryPoint[] {
  return base.map((p) => {
    let v = p.value
    if (p.key === 'temp') v = jitter(p.value, 1.5, 88, 96)
    else if (p.key === 'vibZ') v = jitter(p.value, 5, 28, 42)
    else if (p.key === 'coolFlow') v = jitter(p.value, 3, 6, 8.5)
    let isAnomalous = false
    if (p.threshold !== undefined) {
      if (p.direction === 'below') {
        isAnomalous = v <= p.threshold
      } else {
        isAnomalous = v > p.threshold
      }
    }
    return { ...p, value: v, isAnomalous }
  })
}

/**
 * Hook that drives live telemetry updates:
 * - Every 1.5 seconds in DEMO mode.
 * - Every 3.0 seconds in REAL mode (polling /agent/telemetry/{deviceId}).
 * Removed dependency on `incidents` to prevent interval re-creation on every tick.
 */
export function useLiveTelemetry() {
  const { isDemoMode, updateLiveTelemetry } = useAgenticStore()

  useEffect(() => {
    if (isDemoMode) {
      const id = setInterval(() => {
        const incidents = useAgenticStore.getState().incidents
        const activeIncidents = incidents.filter(
          (i) => (i.status === 'active' || i.status === 'awaiting_approval') && i.telemetry
        )

        if (activeIncidents.length === 0) return

        activeIncidents.forEach((incident) => {
          const device = incident.telemetry!.deviceId
          const base = BASE[device] ?? incident.telemetry!.points
          const updated = tick(base)
          updateLiveTelemetry(device, updated)

          useAgenticStore.setState((s) => ({
            incidents: s.incidents.map((i) =>
              i.id === incident.id && i.telemetry
                ? { ...i, telemetry: { ...i.telemetry, points: updated, timestamp: new Date().toISOString() } }
                : i
            ),
          }))
        })
      }, 1500)

      return () => clearInterval(id)
    } else {
      // Real mode: poll /agent/telemetry/{deviceId} every 3 seconds
      const poll = async () => {
        const state = useAgenticStore.getState()
        const incidents = state.incidents
        const targetDevices = new Set<string>()

        if (state.activeIncident?.device) {
          targetDevices.add(state.activeIncident.device)
        }
        incidents.forEach((inc) => {
          if (inc.status === 'active' || inc.status === 'awaiting_approval') {
            targetDevices.add(inc.device)
          }
        })
        if (targetDevices.size === 0) {
          targetDevices.add('COMP-TB-01')
        }

        for (const device of targetDevices) {
          try {
            const res = await fetch(`/agent/telemetry/${device}`)
            if (!res.ok) continue
            const snapshot = await res.json()
            if (snapshot?.points) {
              updateLiveTelemetry(device, snapshot.points)
              useAgenticStore.setState((s) => ({
                incidents: s.incidents.map((i) =>
                  i.device === device
                    ? { ...i, telemetry: { ...snapshot, timestamp: snapshot.timestamp || new Date().toISOString() } }
                    : i
                ),
                activeIncident:
                  s.activeIncident?.device === device
                    ? {
                      ...s.activeIncident,
                      telemetry: {
                        ...snapshot,
                        timestamp: snapshot.timestamp || new Date().toISOString(),
                      },
                    }
                    : s.activeIncident,
              }))
            }
          } catch {
            // Ignore polling errors in background
          }
        }
      }

      poll()
      const id = setInterval(poll, 3000)
      return () => clearInterval(id)
    }
  }, [isDemoMode, updateLiveTelemetry])
}
