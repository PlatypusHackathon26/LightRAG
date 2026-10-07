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
 * Put local values in lightrag_webui/.env.development.local (gitignored via *.local).
 */
export interface AgentConfig {
  live: boolean
  baseUrl: string
  token?: string
}

export const agentConfig: AgentConfig = {
  live: import.meta.env.VITE_AGENT_LIVE === 'true',
  baseUrl: (import.meta.env.VITE_AGENT_BASE_URL ?? '').replace(/\/+$/, ''),
  token: import.meta.env.VITE_AGENT_TOKEN || undefined,
}
