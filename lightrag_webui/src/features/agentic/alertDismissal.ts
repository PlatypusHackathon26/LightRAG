/**
 * Clearing handled alerts from the sidebar. The gateway sends every alert again on each poll, so a
 * cleared one is remembered (in this browser) by incident id AND the episode's timestamp: the same
 * machine failing again later is a new episode with a new timestamp, and shows up again.
 * Alerts still active or waiting for approval can never be cleared.
 */
import type { Incident } from './types/agentic'

export const DISMISSED_STORAGE_KEY = 'denso-agentic-dismissed-alerts'

/** incident id -> timestamp of the episode the operator cleared */
export type DismissedAlerts = Record<string, string>

export const isHandled = (incident: Incident): boolean =>
  incident.status === 'resolved' || incident.status === 'acknowledged' || incident.status === 'closed'

export const visibleIncidents = (incidents: Incident[], dismissed: DismissedAlerts): Incident[] =>
  incidents.filter((i) => dismissed[i.id] !== i.timestamp)

/** Remember the given alerts as cleared; ones not yet handled are ignored. */
export function dismiss(dismissed: DismissedAlerts, incidents: Incident[]): DismissedAlerts {
  const next = { ...dismissed }
  for (const incident of incidents) if (isHandled(incident)) next[incident.id] = incident.timestamp
  return next
}

export function loadDismissed(storage: Pick<Storage, 'getItem'> | undefined): DismissedAlerts {
  try {
    const parsed: unknown = JSON.parse(storage?.getItem(DISMISSED_STORAGE_KEY) ?? '{}')
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? (parsed as DismissedAlerts) : {}
  } catch {
    return {}
  }
}

export function saveDismissed(storage: Pick<Storage, 'setItem'> | undefined, dismissed: DismissedAlerts): void {
  try {
    storage?.setItem(DISMISSED_STORAGE_KEY, JSON.stringify(dismissed))
  } catch {
    /* blocked storage: cleared alerts come back after a reload */
  }
}
