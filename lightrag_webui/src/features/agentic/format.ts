/** Display helpers for the agentic UI (kept out of component files for fast refresh). */

/** The gateway sends ISO timestamps ("2026-10-08T22:04:05.92+00:00"): show local date and time. */
export function formatImportedAt(value: string): { date: string; time?: string } {
  if (!/^\d{4}-\d{2}-\d{2}T/.test(value)) return { date: value }
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return { date: value }
  const pad = (n: number) => String(n).padStart(2, '0')
  return {
    date: `${pad(d.getDate())}/${pad(d.getMonth() + 1)}/${d.getFullYear()}`,
    time: `${pad(d.getHours())}:${pad(d.getMinutes())}`,
  }
}

/** First page number of a citation's "4" / "4, 7" / "29-36". */
export function firstPage(pages?: string): number | undefined {
  const n = Number(pages?.match(/\d+/)?.[0])
  return Number.isFinite(n) && n > 0 ? n : undefined
}

/** The command a proposed action would run ("SET_RPM", "S=50"), for the approve button. */
export function actionCommand(items: { type: string; params: Record<string, string> }[]): string | undefined {
  const plc = items.find((i) => i.type === 'plc_command')
  return plc?.params['Lệnh'] ?? plc?.params.Command ?? undefined
}
