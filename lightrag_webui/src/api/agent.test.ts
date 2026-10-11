import { describe, expect, test } from 'bun:test'
import { AgentApiError, createAgentClient } from './agent'

/**
 * The agent client switches between mocks and the DENSO Agent Gateway. These
 * pin the live wiring the gateway relies on (paths, bearer token, JSON body)
 * and that mock mode never touches the network.
 */

interface Call {
  url: string
  init?: RequestInit
}

const stubFetch = (respond: (url: string) => Response) => {
  const calls: Call[] = []
  const fetchImpl = (url: string, init?: RequestInit) => {
    calls.push({ url, init })
    return Promise.resolve(respond(url))
  }
  return { calls, fetchImpl }
}

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

describe('agent client', () => {
  test('the original file is fetched with the bearer token, and a 404 is an AgentApiError', async () => {
    const { calls, fetchImpl } = stubFetch((url) =>
      url.includes('doc-1')
        ? new Response('%PDF-1.4', { headers: { 'Content-Type': 'application/pdf' } })
        : new Response('{}', { status: 404 })
    )
    const client = createAgentClient({ live: true, baseUrl: 'http://gw', token: 'tok' }, fetchImpl)
    const blob = await client.fetchDocumentFile('doc-1')
    expect(blob.type).toBe('application/pdf')
    expect(await blob.text()).toBe('%PDF-1.4')
    expect(calls[0].url).toBe('http://gw/agent/documents/doc-1/file')
    expect((calls[0].init?.headers as Record<string, string>).Authorization).toBe('Bearer tok')
    const err = await client.fetchDocumentFile('gone').catch((e) => e)
    expect(err instanceof AgentApiError && err.status === 404).toBe(true)
  })

  test('mock mode answers locally without calling fetch', async () => {
    const { calls, fetchImpl } = stubFetch(() => json({}))
    const client = createAgentClient({ live: false, baseUrl: 'http://gw' }, fetchImpl)
    const reply = await client.postAgentChat({ conversationId: 'c1', message: 'hi' })
    expect(reply.content.startsWith('[DEMO]')).toBe(true)
    expect((await client.fetchDocuments()).length > 0).toBe(true)
    expect(calls.length).toBe(0)
  })

  test('live chat posts JSON to the gateway with the bearer token', async () => {
    const { calls, fetchImpl } = stubFetch(() =>
      json({
        content: 'Tighten to 6.9-10.8 Nm.',
        citations: [{ id: 'cit-1', documentId: 'Diesel_SCV', documentName: 'Diesel_SCV', pages: '4' }],
        events: [{ id: 'ev-1', timestamp: '2026-10-07T05:00:00Z', type: 'knowledge_retrieved', label: 'Retrieved 1' }],
      })
    )
    const client = createAgentClient({ live: true, baseUrl: 'http://gw', token: 'tok' }, fetchImpl)
    const reply = await client.postAgentChat({ conversationId: 'c1', message: 'torque?' })

    expect(calls.length).toBe(1)
    expect(calls[0].url).toBe('http://gw/agent/chat')
    expect(calls[0].init?.method).toBe('POST')
    const headers = calls[0].init?.headers as Record<string, string>
    expect(headers.Authorization).toBe('Bearer tok')
    expect(headers['Content-Type']).toBe('application/json')
    expect(JSON.parse(String(calls[0].init?.body))).toEqual({ conversationId: 'c1', message: 'torque?' })
    expect(reply.citations?.[0].pages).toBe('4')
    expect(reply.events?.length).toBe(1)
  })

  test('live errors carry status and the gateway detail', async () => {
    const { fetchImpl } = stubFetch(() => json({ detail: 'LightRAG level_1 server is not running' }, 503))
    const client = createAgentClient({ live: true, baseUrl: '' }, fetchImpl)
    let caught: unknown
    try {
      await client.postAgentChat({ conversationId: 'c1', message: 'x' })
    } catch (e) {
      caught = e
    }
    expect(caught instanceof AgentApiError).toBe(true)
    expect((caught as AgentApiError).status).toBe(503)
    expect((caught as AgentApiError).message.includes('not running')).toBe(true)
  })

  test('a missing incident or telemetry snapshot is undefined, not an error', async () => {
    const { fetchImpl } = stubFetch(() => json({ detail: 'not found' }, 404))
    const client = createAgentClient({ live: true, baseUrl: '' }, fetchImpl)
    expect((await client.fetchIncident('nope')) === undefined).toBe(true)
    expect((await client.fetchTelemetry('nope')) === undefined).toBe(true)
  })

  test('documents come from GET /agent/documents without a token when none is set', async () => {
    const { calls, fetchImpl } = stubFetch(() => json([]))
    const client = createAgentClient({ live: true, baseUrl: 'http://gw' }, fetchImpl)
    await client.fetchDocuments()
    expect(calls[0].url).toBe('http://gw/agent/documents')
    expect('Authorization' in (calls[0].init?.headers as Record<string, string>)).toBe(false)
  })

  test('upload sends multipart with the token, without a JSON content type', async () => {
    const job = { id: 'j1', name: 'manual.pdf', level: 1, status: 'uploading', progress: 0, stage: 'queued',
      images: 'pending', error: null, elapsedSeconds: 0 }
    const { calls, fetchImpl } = stubFetch((url) => json(url.endsWith('/agent/documents') ? { jobId: 'j1', job } : job))
    const client = createAgentClient({ live: true, baseUrl: 'http://gw', token: 'tok' }, fetchImpl)
    const got = await client.uploadDocument(new File(['%PDF'], 'manual.pdf'), 1)
    expect(got.id).toBe('j1')
    const init = calls[0].init as RequestInit
    const headers = init.headers as Record<string, string>
    expect(calls[0].url).toBe('http://gw/agent/documents')
    expect(init.body instanceof FormData).toBe(true)
    expect(headers['Content-Type'] === undefined).toBe(true) // the browser adds the multipart boundary
    expect(headers.Authorization).toBe('Bearer tok')
    await client.fetchUploadJob('j1')
    expect(calls[1].url).toBe('http://gw/agent/documents/jobs/j1')
  })
})
