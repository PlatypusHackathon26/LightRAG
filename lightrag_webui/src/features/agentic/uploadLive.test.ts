import { describe, expect, test } from 'bun:test'
import { AgentApiError, type UploadJob } from '../../api/agent'
import type { KnowledgeDocument } from './types/agentic'
import { deleteLive, uploadLive } from './uploadLive'

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

describe('deleteLive', () => {
  test('the row goes only after the server confirms the deletion', async () => {
    const order: string[] = []
    const client = { deleteDocument: async (id: string) => { order.push(`server:${id}`); return { status: 'deleted', levels: ['level_1'] } } }
    await deleteLive('doc-1', (id) => order.push(`row:${id}`), () => {}, client)
    expect(order).toEqual(['server:doc-1', 'row:doc-1'])
  })

  test('a refused deletion keeps the row and says why', async () => {
    const notes: string[] = []
    let removed = false
    const client = { deleteDocument: async () => { throw new AgentApiError('DELETE failed: 409 - busy', 409) } }
    await deleteLive('doc-1', () => { removed = true }, (_id, patch) => notes.push(patch.statusNote ?? ''), client)
    expect(removed).toBe(false)
    expect(notes[notes.length - 1]).toBe('Xóa lỗi: DELETE failed: 409 - busy')
  })
})

describe('upload row ids (seen live: deleting a fresh upload sent its placeholder id, 404)', () => {
  test('a finished upload reloads the list so the row gets the real document id', async () => {
    let reloaded = 0
    const client = {
      uploadDocument: async () => job({ status: 'vectorized', progress: 100, images: 'done' }),
      fetchUploadJob: async () => job({}),
    }
    const h = harness()
    await uploadLive(new File(['%PDF'], 'manual.pdf'), h.add, h.update, client, async () => {}, async () => { reloaded++ })
    expect(reloaded).toBe(1)
  })

  test('a failed upload does not reload', async () => {
    let reloaded = 0
    const client = { uploadDocument: async () => job({ status: 'error', error: 'boom' }), fetchUploadJob: async () => job({}) }
    const h = harness()
    await uploadLive(new File(['%PDF'], 'manual.pdf'), h.add, h.update, client, async () => {}, async () => { reloaded++ })
    expect(reloaded).toBe(0)
  })

  test('deleting a placeholder row never reaches the gateway', async () => {
    let called = false
    const notes: string[] = []
    const client = { deleteDocument: async () => { called = true; return { status: 'deleted', levels: [] } } }
    await deleteLive('doc-upload-123-abc', () => {}, (_id, p) => notes.push(p.statusNote ?? ''), client)
    expect(called).toBe(false)
    expect(notes[0].startsWith('Tài liệu đang được xử lý')).toBe(true)
  })
})
