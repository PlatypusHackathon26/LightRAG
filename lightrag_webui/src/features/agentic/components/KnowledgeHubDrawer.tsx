import { useCallback } from 'react'
import { useDropzone } from 'react-dropzone'
import { useAgenticStore } from '../stores/agenticStore'
import type { KnowledgeDocument } from '../types/agentic'
import { agentClient } from '../../../api/agent'
import { deleteLive, uploadLive } from '../uploadLive'
import SourcePreviewModal from './SourcePreviewModal'
import { formatImportedAt } from '../format'
import {
  XIcon,
  UploadCloudIcon,
  FileTextIcon,
  EyeIcon,
  Trash2Icon,
  CheckCircle2Icon,
  LoaderIcon,
  AlertCircleIcon,
} from 'lucide-react'

const STATUS_COLOR: Record<KnowledgeDocument['indexStatus'], string> = {
  uploading: '#F59E0B',
  parsing: '#3B82F6',
  chunking: '#8B5CF6',
  embedding: '#06B6D4',
  vectorized: '#10B981',
  error: '#EF4444',
  cancelled: '#64748B',
}

const STATUS_LABEL: Record<KnowledgeDocument['indexStatus'], string> = {
  uploading: 'Uploading',
  parsing: 'Parsing',
  chunking: 'Chunking',
  embedding: 'Embedding',
  vectorized: 'Vectorized',
  error: 'Error',
  cancelled: 'Cancelled',
}

const PIPELINE_STAGES: KnowledgeDocument['indexStatus'][] = [
  'uploading',
  'parsing',
  'chunking',
  'embedding',
  'vectorized',
]

function formatBytes(b: number): string {
  if (b < 1024) return `${b} B`
  if (b < 1024 * 1024) return `${(b / 1024).toFixed(1)} KB`
  return `${(b / (1024 * 1024)).toFixed(1)} MB`
}

function simulateUploadPipeline(
  id: string,
  updateDocumentStatus: (id: string, status: KnowledgeDocument['indexStatus'], progress?: number) => void
) {
  const delays = [500, 800, 1000, 1200, 800]
  let cumulativeDelay = 0

  PIPELINE_STAGES.forEach((stage, idx) => {
    cumulativeDelay += delays[idx]
    setTimeout(() => {
      const progress = Math.round(((idx + 1) / PIPELINE_STAGES.length) * 100)
      updateDocumentStatus(id, stage, progress)
    }, cumulativeDelay)
  })
}

function DocumentRow({
  doc,
  onPreview,
  onDelete,
}: {
  doc: KnowledgeDocument
  onPreview: (id: string) => void
  onDelete: (id: string) => void
}) {
  const statusColor = STATUS_COLOR[doc.indexStatus]
  const imported = formatImportedAt(doc.importedAt)
  const isProcessing = doc.indexStatus !== 'vectorized' && doc.indexStatus !== 'error' && doc.indexStatus !== 'cancelled'

  return (
    <tr
      style={{ borderBottom: '1px solid #1E293B' }}
    >
      <td className="py-2 pr-3" style={{ width: '40%' }}>
        <div className="flex items-center gap-1.5">
          <FileTextIcon size={12} style={{ color: '#06B6D4', flexShrink: 0 }} />
          <span
            className="font-medium truncate"
            style={{ fontSize: 13, color: '#E2E8F0', fontFamily: 'Inter, sans-serif' }}
            title={doc.name}
          >
            {doc.name}
          </span>
        </div>
        <div className="flex flex-wrap gap-1 mt-0.5">
          {doc.tags.slice(0, 3).map((tag) => (
            <span
              key={tag}
              className="rounded px-1 py-0.5"
              style={{ fontSize: 10, background: '#083344', color: '#06B6D4', fontFamily: 'Roboto Mono, monospace' }}
            >
              {tag}
            </span>
          ))}
          {doc.tags.length > 3 && (
            <span
              style={{ fontSize: 10, color: '#94A3B8', fontFamily: 'Roboto Mono, monospace' }}
            >
              +{doc.tags.length - 3}
            </span>
          )}
        </div>
        {doc.statusNote && (
          <div
            className="mt-0.5 max-w-[260px]"
            style={{ fontSize: 11, color: doc.indexStatus === 'error' ? '#EF4444' : '#94A3B8', fontFamily: 'Inter, sans-serif' }}
          >
            {doc.statusNote}
          </div>
        )}
      </td>
      <td className="py-2 pr-3 whitespace-nowrap" style={{ width: '12%' }}>
        <span style={{ fontSize: 12, color: '#94A3B8', fontFamily: 'Roboto Mono, monospace' }}>
          {formatBytes(doc.sizeBytes)}
        </span>
      </td>
      <td className="py-2 pr-3 whitespace-nowrap" style={{ width: '16%' }}>
        <div style={{ fontSize: 12, color: '#94A3B8', fontFamily: 'Roboto Mono, monospace' }} title={doc.importedAt}>
          {imported.date}
        </div>
        {imported.time && (
          <div style={{ fontSize: 11, color: '#64748B', fontFamily: 'Roboto Mono, monospace' }}>{imported.time}</div>
        )}
      </td>
      <td className="py-2 pr-3 whitespace-nowrap" style={{ width: '18%' }}>
        <div className="flex items-center gap-1.5">
          {isProcessing ? (
            <LoaderIcon size={11} className="animate-spin" style={{ color: statusColor }} />
          ) : doc.indexStatus === 'vectorized' ? (
            <CheckCircle2Icon size={11} style={{ color: statusColor }} />
          ) : (
            <AlertCircleIcon size={11} style={{ color: statusColor }} />
          )}
          <span
            className="font-medium"
            style={{ fontSize: 12, color: statusColor, fontFamily: 'Roboto Mono, monospace' }}
          >
            {STATUS_LABEL[doc.indexStatus]}
          </span>
        </div>
        {isProcessing && doc.progress !== undefined && (
          <div
            className="mt-0.5 rounded-full overflow-hidden"
            style={{ height: 3, background: '#1E293B', width: 60 }}
          >
            <div
              className="h-full rounded-full transition-all"
              style={{ width: `${doc.progress}%`, background: statusColor }}
            />
          </div>
        )}
      </td>
      <td className="py-2 whitespace-nowrap" style={{ width: '14%' }}>
        <div className="flex items-center gap-1">
          <button
            id={`doc-preview-${doc.id}`}
            aria-label={`Preview document ${doc.name}`}
            onClick={() => onPreview(doc.id)}
            disabled={doc.indexStatus !== 'vectorized'}
            className="rounded p-1 transition-colors hover:bg-[#083344] focus-visible:outline-2 focus-visible:outline-[#06B6D4] disabled:opacity-40 disabled:cursor-not-allowed"
            title="Preview extracted text"
          >
            <EyeIcon size={13} style={{ color: '#06B6D4' }} />
          </button>
          <button
            id={`doc-delete-${doc.id}`}
            aria-label={`Delete document ${doc.name}`}
            onClick={() => onDelete(doc.id)}
            className="rounded p-1 transition-colors hover:bg-[#2A1215] focus-visible:outline-2 focus-visible:outline-[#EF4444]"
            title="Delete document"
          >
            <Trash2Icon size={13} style={{ color: '#EF4444' }} />
          </button>
        </div>
      </td>
    </tr>
  )
}

export default function KnowledgeHubDrawer() {
  const {
    knowledgeDrawerOpen,
    setKnowledgeDrawerOpen,
    documents,
    addDocument,
    updateDocument,
    refreshDocuments,
    updateDocumentStatus,
    deleteDocument,
    previewDocumentId,
    setPreviewDocumentId,
  } = useAgenticStore()

  const previewDoc = documents.find((d) => d.id === previewDocumentId) ?? null

  const onDrop = useCallback(
    (accepted: File[]) => {
      if (agentClient.live) {
        accepted.forEach((file) =>
          uploadLive(file, addDocument, updateDocument, agentClient, undefined, () => refreshDocuments(() => agentClient.fetchDocuments()))
        )
        return
      }
      accepted.forEach((file) => {
        const id = `doc-upload-${Date.now()}-${Math.random().toString(36).slice(2)}`
        const newDoc: KnowledgeDocument = {
          id,
          name: file.name,
          tags: ['#Uploaded'],
          sizeBytes: file.size,
          importedAt: new Date().toLocaleDateString('vi-VN', { day: '2-digit', month: '2-digit', year: 'numeric' }),
          indexStatus: 'uploading',
          progress: 0,
          file: file,
          extractedText: `(Simulated extracted text for ${file.name})\n\nIn a real deployment, this document would be parsed, chunked, and embedded into the LightRAG knowledge base.\n\nFile size: ${(file.size / 1024).toFixed(1)} KB\nFile type: ${file.type || 'unknown'}`,
        }
        addDocument(newDoc)
        simulateUploadPipeline(id, updateDocumentStatus)
      })
    },
    [addDocument, updateDocument, updateDocumentStatus, refreshDocuments]
  )

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    // Live: what the gateway pipeline accepts (denso/gateway/jobs.py ALLOWED).
    accept: agentClient.live
      ? {
        'application/pdf': ['.pdf'],
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document': ['.docx'],
        'application/vnd.openxmlformats-officedocument.presentationml.presentation': ['.pptx'],
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'],
        'text/html': ['.html'],
        'text/markdown': ['.md'],
        'text/plain': ['.txt'],
        'image/*': ['.png', '.jpg', '.jpeg', '.tiff', '.bmp', '.webp'],
      }
      : {
        'application/pdf': ['.pdf'],
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document': ['.docx'],
        'text/plain': ['.txt'],
        'text/csv': ['.csv'],
      },
    multiple: true,
  })

  if (!knowledgeDrawerOpen) return null

  return (
    <>
      {/* Overlay */}
      <div
        className="fixed inset-0 z-30"
        onClick={() => setKnowledgeDrawerOpen(false)}
        style={{ background: 'rgba(15,23,42,0.25)' }}
        aria-hidden="true"
      />

      {/* Drawer */}
      <div
        id="knowledge-hub-drawer"
        role="dialog"
        aria-modal="true"
        aria-label="Knowledge Hub"
        className="fixed top-0 right-0 bottom-0 z-40 flex flex-col overflow-hidden"
        style={{
          width: 650,
          background: '#0B1220',
          borderLeft: '1px solid #263347',
          boxShadow: '-12px 0 40px rgba(0,0,0,0.12)',
          animation: 'slideInRight 0.25s ease-out',
        }}
      >
        {/* Header */}
        <div
          className="px-4 py-3 flex items-center justify-between shrink-0"
          style={{ borderBottom: '1px solid #263347', background: '#111A2C' }}
        >
          <div>
            <div className="font-bold" style={{ fontSize: 16, color: '#E2E8F0', fontFamily: 'Inter, sans-serif' }}>
              Knowledge Hub
            </div>
            <div style={{ fontSize: 12, color: '#94A3B8', fontFamily: 'Roboto Mono, monospace' }}>
              {documents.filter((d) => d.indexStatus === 'vectorized').length} vectorized &nbsp;·&nbsp; {documents.length} total
            </div>
          </div>
          <button
            aria-label="Close Knowledge Hub"
            onClick={() => setKnowledgeDrawerOpen(false)}
            className="rounded p-1.5 transition-colors hover:bg-[#1E293B] focus-visible:outline-2 focus-visible:outline-[#06B6D4]"
          >
            <XIcon size={16} style={{ color: '#94A3B8' }} />
          </button>
        </div>

        {/* Upload zone */}
        <div className="px-4 py-3 shrink-0" style={{ borderBottom: '1px solid #263347' }}>
          <div
            {...getRootProps()}
            id="knowledge-upload-dropzone"
            className="rounded border-2 border-dashed px-4 py-5 text-center cursor-pointer transition-all focus-visible:outline-2 focus-visible:outline-[#06B6D4]"
            style={{
              borderColor: isDragActive ? '#06B6D4' : '#263347',
              background: isDragActive ? '#083344' : '#111A2C',
            }}
            tabIndex={0}
            role="button"
            aria-label="Drop files here or click to upload. Accepted: PDF, DOCX, TXT, CSV"
          >
            <input {...getInputProps()} />
            <UploadCloudIcon
              size={24}
              style={{ color: isDragActive ? '#06B6D4' : '#64748B', margin: '0 auto 8px' }}
            />
            <div className="font-medium" style={{ fontSize: 13, color: isDragActive ? '#06B6D4' : '#94A3B8', fontFamily: 'Inter, sans-serif' }}>
              {isDragActive ? 'Drop files here' : 'Drag & drop or click to upload'}
            </div>
            <div className="mt-1" style={{ fontSize: 11, color: '#64748B', fontFamily: 'Roboto Mono, monospace' }}>
              PDF · DOCX · TXT · CSV
            </div>
          </div>
        </div>

        {/* Document table */}
        <div className="flex-1 overflow-y-auto scrollbar-thin px-4 py-3">
          <table className="w-full" style={{ borderCollapse: 'collapse', tableLayout: 'fixed' }}>
            <thead>
              <tr style={{ borderBottom: '1px solid #263347' }}>
                <th className="pb-2 text-left uppercase tracking-wider" style={{ fontSize: 11, color: '#94A3B8', fontFamily: 'Roboto Mono, monospace', width: '40%' }}>
                  Document
                </th>
                <th className="pb-2 text-left uppercase tracking-wider" style={{ fontSize: 11, color: '#94A3B8', fontFamily: 'Roboto Mono, monospace', width: '12%' }}>
                  Size
                </th>
                <th className="pb-2 text-left uppercase tracking-wider" style={{ fontSize: 11, color: '#94A3B8', fontFamily: 'Roboto Mono, monospace', width: '16%' }}>
                  Imported
                </th>
                <th className="pb-2 text-left uppercase tracking-wider" style={{ fontSize: 11, color: '#94A3B8', fontFamily: 'Roboto Mono, monospace', width: '18%' }}>
                  Status
                </th>
                <th className="pb-2 text-left uppercase tracking-wider" style={{ fontSize: 11, color: '#94A3B8', fontFamily: 'Roboto Mono, monospace', width: '14%' }}>
                  Actions
                </th>
              </tr>
            </thead>
            <tbody>
              {documents.map((doc) => (
                <DocumentRow
                  key={doc.id}
                  doc={doc}
                  onPreview={(id) => setPreviewDocumentId(id)}
                  onDelete={(id) => (agentClient.live ? deleteLive(id, deleteDocument, updateDocument, agentClient, doc.jobId) : deleteDocument(id))}
                />
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Preview Modal */}
      <SourcePreviewModal doc={previewDoc} onClose={() => setPreviewDocumentId(null)} />
    </>
  )
}
