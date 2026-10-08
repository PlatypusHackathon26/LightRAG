import { describe, expect, test } from 'bun:test'
import { AgentApiError, type UploadJob } from '../../api/agent'
import type { KnowledgeDocument } from './types/agentic'
import { uploadLive } from './uploadLive'

const job = (patch: Partial<UploadJob>): UploadJob => ({
  id: 'j1', name: 'manual.pdf', level: 1, status: 'parsing', progress: 10, stage: 'Docling',
  images: 'pending', error: null, elapsedSeconds: 75, ...patch,
})

function harness() {
  const docs: KnowledgeDocument[] = []
  const add = (d: KnowledgeDocument) => docs.push(d)
  const update = (id: string, patch: Partial<KnowledgeDocument>) => {
    const i = docs.findIndex((d) => d.id === id)
    docs[i] = { ...docs[i], ...patch }
  }
  return { docs, add, update }
}

describe('uploadLive', () => {
  test('follows the job until the image pass is done', async () => {
    const steps = [
      job({ status: 'chunking', progress: 60 }),
      job({ status: 'vectorized', progress: 100, images: 'running', stage: 'Sẵn sàng hỏi đáp; đang đọc ảnh' }),
      job({ status: 'vectorized', progress: 100, images: 'done', stage: 'Sẵn sàng hỏi đáp (đã gồm chữ trong ảnh)' }),
    ]
    let polls = 0
    const client = {
      uploadDocument: async () => job({ status: 'uploading', progress: 0 }),
      fetchUploadJob: async () => steps[polls++],
    }
    const h = harness()
    await uploadLive(new File(['%PDF'], 'manual.pdf'), h.add, h.update, client, async () => {})
    expect(polls).toBe(3)
    expect(h.docs[0].indexStatus).toBe('vectorized')
    expect(h.docs[0].statusNote).toBe('Sẵn sàng hỏi đáp (đã gồm chữ trong ảnh) · 1 phút 15 giây')
  })

  test('a pipeline error ends the polling and shows the reason', async () => {
    const client = {
      uploadDocument: async () => job({}),
      fetchUploadJob: async () => job({ status: 'error', error: 'Docling is not running' }),
    }
    const h = harness()
    await uploadLive(new File(['%PDF'], 'manual.pdf'), h.add, h.update, client, async () => {})
    expect(h.docs[0].indexStatus).toBe('error')
    expect(h.docs[0].statusNote?.startsWith('Docling is not running')).toBe(true)
  })

  test('a user without upload rights gets a plain message', async () => {
    const client = {
      uploadDocument: async () => { throw new AgentApiError('POST /agent/documents failed: 403', 403) },
      fetchUploadJob: async () => job({}),
    }
    const h = harness()
    await uploadLive(new File(['%PDF'], 'manual.pdf'), h.add, h.update, client, async () => {})
    expect(h.docs[0].statusNote).toBe('Tài khoản này không có quyền upload tài liệu')
  })
})
