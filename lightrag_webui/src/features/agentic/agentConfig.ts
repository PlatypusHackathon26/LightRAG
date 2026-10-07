/**
 * Agent backend switches for the agentic UI.
 *
 * - VITE_AGENT_LIVE=true      call the DENSO Agent Gateway (denso/gateway) instead of mocks.
 *                             Independent of VITE_DEMO_MODE, which only decides whether the
 *                             main LightRAG UI is replaced by the agentic workspace.
 * - VITE_AGENT_BASE_URL       gateway origin, e.g. http://127.0.0.1:9700 (the gateway allows
 *                             CORS from the Vite dev server). Empty = same origin.
 * - VITE_AGENT_TOKEN          optional bearer token mapped to an access level by the gateway's
 *                             users.json. Dev/demo only: anything in a VITE_ variable ships in
 *                             the bundle, so real deployments must log users in instead.
 *
 * Runtime override (hosted demo): open the page with `?gateway=https://xxx.trycloudflare.com`.
 * The value is remembered in localStorage, so a new tunnel URL needs a new link, not a new
 * build; `?gateway=` (empty) forgets it and falls back to VITE_AGENT_BASE_URL.
 *
 * Put local values in lightrag_webui/.env.development.local (gitignored via *.local).
 */
export interface AgentConfig {
  live: boolean
  baseUrl: string
  token?: string
}

export const GATEWAY_STORAGE_KEY = 'denso-agent-gateway'

type StorageLike = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>

const trimSlash = (url: string) => url.replace(/\/+$/, '')

/** Gateway origin: `?gateway=` in the URL, else the remembered one, else the build-time value. */
export function resolveGatewayUrl(envUrl: string, search: string, storage?: StorageLike): string {
  const param = new URLSearchParams(search).get('gateway')
  try {
    if (param !== null) {
      const url = param.trim()
      if (/^https?:\/\/[^\s/]+/.test(url)) {
        storage?.setItem(GATEWAY_STORAGE_KEY, trimSlash(url))
        return trimSlash(url)
      }
      if (url === '') storage?.removeItem(GATEWAY_STORAGE_KEY)
    }
    const remembered = storage?.getItem(GATEWAY_STORAGE_KEY)
    if (remembered) return remembered
  } catch {
    /* storage blocked (private window): use the URL parameter or the build value */
    if (param && /^https?:\/\/[^\s/]+/.test(param.trim())) return trimSlash(param.trim())
  }
  return trimSlash(envUrl)
}

function browserStorage(): StorageLike | undefined {
  try {
    return typeof window !== 'undefined' ? window.localStorage : undefined
  } catch {
    return undefined
  }
}

export const agentConfig: AgentConfig = {
  live: import.meta.env.VITE_AGENT_LIVE === 'true',
  baseUrl: resolveGatewayUrl(
    import.meta.env.VITE_AGENT_BASE_URL ?? '',
    typeof window !== 'undefined' ? window.location.search : '',
    browserStorage()
  ),
  token: import.meta.env.VITE_AGENT_TOKEN || undefined,
}
