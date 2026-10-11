/**
 * Live Knowledge Hub upload: send a file through the gateway's DENSO pipeline
 * (denso/gateway/jobs.py) and mirror its job on the document row until it is done.
 */
import { agentClient, AgentApiError, uploadJobActive, type UploadJob } from '../../api/agent'
import type { KnowledgeDocument } from './types/agentic'
import { UPLOAD_ROW_PREFIX } from './stores/agenticStore'

export const POLL_MS = 3000

export function jobNote(job: UploadJob): string {
  const minutes = Math.floor(job.elapsedSeconds / 60)
  const elapsed = minutes ? `${minutes} phút ${job.elapsedSeconds % 60} giây` : `${job.elapsedSeconds} giây`
  return `${job.error ?? job.stage} · ${elapsed}`
}

/** Live mode: send the file through the gateway pipeline and follow its job until done. */
export async function uploadLive(
  file: File,
  addDocument: (doc: KnowledgeDocument) => void,
  updateDocument: (id: string, patch: Partial<KnowledgeDocument>) => void,
  client: Pick<typeof agentClient, 'uploadDocument' | 'fetchUploadJob'> = agentClient,
  wait: (ms: number) => Promise<void> = (ms) => new Promise((r) => setTimeout(r, ms)),
  /** Called once the job is finished: reload the list so the row carries the document's real id. */
  onDone?: () => Promise<void>
): Promise<void> {
  const id = `${UPLOAD_ROW_PREFIX}${Date.now()}-${Math.random().toString(36).slice(2)}`
  addDocument({
    id,
    name: file.name,
    tags: ['#Uploaded'],
    sizeBytes: file.size,
    importedAt: new Date().toLocaleDateString('vi-VN', { day: '2-digit', month: '2-digit', year: 'numeric' }),
    indexStatus: 'uploading',
    progress: 0,
    statusNote: 'Đang gửi file lên gateway…',
  })
  try {
    let job = await client.uploadDocument(file)
    updateDocument(id, { jobId: job.id })
    for (;;) {
      updateDocument(id, { indexStatus: job.status, progress: job.progress, statusNote: jobNote(job) })
      if (!uploadJobActive(job)) {
        if (job.status === 'vectorized' && onDone) await onDone().catch(() => undefined)
        return
      }
      await wait(POLL_MS)
      job = await client.fetchUploadJob(job.id)
    }
  } catch (e) {
    const message = e instanceof AgentApiError && e.status === 403
      ? 'Tài khoản này không có quyền upload tài liệu'
      : `Upload lỗi: ${e instanceof Error ? e.message : String(e)}`
    updateDocument(id, { indexStatus: 'error', statusNote: message })
  }
}


/**
 * Live mode: delete the document on the server first; the row goes only once the gateway
 * confirms. (The mock UI dropped the row and left the document answering questions.)
 */
export async function deleteLive(
  id: string,
  removeDocument: (id: string) => void,
  updateDocument: (id: string, patch: Partial<KnowledgeDocument>) => void,
  client: Pick<typeof agentClient, 'deleteDocument'> = agentClient,
  /** The gateway job behind a browser placeholder row (KnowledgeDocument.jobId). */
  jobId?: string
): Promise<void> {
  // A row still being processed is cancelled: the gateway stops its pipeline, then removes what it wrote.
  const processing = id.startsWith(UPLOAD_ROW_PREFIX) || id.startsWith('job-')
  let target = id
  if (id.startsWith(UPLOAD_ROW_PREFIX)) {
    // The browser's placeholder: cancellable once the gateway has answered with its job id.
    if (!jobId) {
      updateDocument(id, { statusNote: 'File đang được gửi lên – bấm xoá lại khi gửi xong để huỷ' })
      return
    }
    target = `job-${jobId}`
  }
  updateDocument(id, { statusNote: processing ? 'Đang dừng xử lý và xoá…' : 'Đang xóa khỏi kho tri thức…' })
  try {
    await client.deleteDocument(target)
    removeDocument(id)
  } catch (e) {
    const message = e instanceof AgentApiError && e.status === 403
      ? 'Tài khoản này không có quyền xóa tài liệu'
      : `Xóa lỗi: ${e instanceof Error ? e.message : String(e)}`
    updateDocument(id, { statusNote: message })
  }
}
