import { useCallback } from 'react'
import { useDropzone } from 'react-dropzone'
import { useAgenticStore } from '../stores/agenticStore'
import type { KnowledgeDocument } from '../types/agentic'
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
  embedding: '#00A896',
  vectorized: '#10B981',
  error: '#EF4444',
}

const STATUS_LABEL: Record<KnowledgeDocument['indexStatus'], string> = {
  uploading: 'Uploading',
  parsing: 'Parsing',
  chunking: 'Chunking',
  embedding: 'Embedding',
  vectorized: 'Vectorized',
  error: 'Error',
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
  const isProcessing = doc.indexStatus !== 'vectorized' && doc.indexStatus !== 'error'

  return (
    <tr
      style={{ borderBottom: '1px solid #3A506B20' }}
    >
      <td className="py-2 pr-3">
        <div className="flex items-center gap-1.5">
          <FileTextIcon size={12} style={{ color: '#00A896', flexShrink: 0 }} />
          <span
            className="text-xs font-medium truncate max-w-[180px]"
            style={{ color: '#e2e8f0', fontFamily: 'Inter, sans-serif' }}
            title={doc.name}
          >
            {doc.name}
          </span>
        </div>
        <div className="flex flex-wrap gap-1 mt-0.5">
          {doc.tags.map((tag) => (
            <span
              key={tag}
              className="text-[9px] rounded px-1 py-0.5"
              style={{ background: '#00A89615', color: '#00A896', fontFamily: 'Roboto Mono, monospace' }}
            >
              {tag}
            </span>
          ))}
        </div>
      </td>
      <td className="py-2 pr-3 whitespace-nowrap">
        <span className="text-[10px]" style={{ color: '#8a9ab5', fontFamily: 'Roboto Mono, monospace' }}>
          {formatBytes(doc.sizeBytes)}
        </span>
      </td>
      <td className="py-2 pr-3 whitespace-nowrap">
        <span className="text-[10px]" style={{ color: '#8a9ab5', fontFamily: 'Roboto Mono, monospace' }}>
          {doc.importedAt}
        </span>
      </td>
      <td className="py-2 pr-3">
        <div className="flex items-center gap-1.5">
          {isProcessing ? (
            <LoaderIcon size={10} className="animate-spin" style={{ color: statusColor }} />
          ) : doc.indexStatus === 'vectorized' ? (
            <CheckCircle2Icon size={10} style={{ color: statusColor }} />
          ) : (
            <AlertCircleIcon size={10} style={{ color: statusColor }} />
          )}
          <span
            className="text-[10px] font-medium"
            style={{ color: statusColor, fontFamily: 'Roboto Mono, monospace' }}
          >
            {STATUS_LABEL[doc.indexStatus]}
          </span>
        </div>
        {isProcessing && doc.progress !== undefined && (
          <div
            className="mt-0.5 rounded-full overflow-hidden"
            style={{ height: 2, background: '#3A506B', width: 60 }}
          >
            <div
              className="h-full rounded-full transition-all"
              style={{ width: `${doc.progress}%`, background: statusColor }}
            />
          </div>
        )}
      </td>
      <td className="py-2">
        <div className="flex items-center gap-1">
          <button
            id={`doc-preview-${doc.id}`}
            aria-label={`Preview document ${doc.name}`}
            onClick={() => onPreview(doc.id)}
            disabled={doc.indexStatus !== 'vectorized'}
            className="rounded p-1 transition-colors hover:bg-[#1C2541] focus-visible:outline-2 focus-visible:outline-[#00A896] disabled:opacity-40 disabled:cursor-not-allowed"
            title="Preview extracted text"
          >
            <EyeIcon size={13} style={{ color: '#00A896' }} />
          </button>
          <button
            id={`doc-delete-${doc.id}`}
            aria-label={`Delete document ${doc.name}`}
            onClick={() => onDelete(doc.id)}
            className="rounded p-1 transition-colors hover:bg-[#EF444420] focus-visible:outline-2 focus-visible:outline-[#EF4444]"
            title="Delete document"
          >
            <Trash2Icon size={13} style={{ color: '#EF4444' }} />
          </button>
        </div>
      </td>
    </tr>
  )
}

function PreviewModal({
  doc,
  onClose,
}: {
  doc: KnowledgeDocument | null
  onClose: () => void
}) {
  if (!doc) return null
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ background: '#0B132B99', backdropFilter: 'blur(4px)' }}
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label={`Preview: ${doc.name}`}
    >
      <div
        className="rounded overflow-hidden flex flex-col"
        style={{
          maxWidth: 640,
          width: '90vw',
          maxHeight: '80vh',
          background: '#1C2541',
          border: '1px solid #3A506B',
          boxShadow: '0 20px 60px #00000080',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div
          className="flex items-center justify-between px-4 py-3"
          style={{ borderBottom: '1px solid #3A506B' }}
        >
          <div className="flex items-center gap-2">
            <FileTextIcon size={14} style={{ color: '#00A896' }} />
            <span className="text-sm font-semibold" style={{ color: '#e2e8f0', fontFamily: 'Inter, sans-serif' }}>
              {doc.name}
            </span>
          </div>
          <button
            aria-label="Close preview"
            onClick={onClose}
            className="rounded p-1 hover:bg-[#3A506B]/40 transition-colors focus-visible:outline-2 focus-visible:outline-[#00A896]"
          >
            <XIcon size={14} style={{ color: '#8a9ab5' }} />
          </button>
        </div>
        <div className="flex-1 overflow-auto p-4">
          <pre
            className="text-xs leading-relaxed whitespace-pre-wrap"
            style={{ color: '#94a3b8', fontFamily: 'Roboto Mono, monospace' }}
          >
            {doc.extractedText ?? '(No extracted text available)'}
          </pre>
        </div>
      </div>
    </div>
  )
}

export default function KnowledgeHubDrawer() {
  const {
    knowledgeDrawerOpen,
    setKnowledgeDrawerOpen,
    documents,
    addDocument,
    updateDocumentStatus,
    deleteDocument,
    previewDocumentId,
    setPreviewDocumentId,
  } = useAgenticStore()

  const previewDoc = documents.find((d) => d.id === previewDocumentId) ?? null

  const onDrop = useCallback(
    (accepted: File[]) => {
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
          extractedText: `(Simulated extracted text for ${file.name})\n\nIn a real deployment, this document would be parsed, chunked, and embedded into the LightRAG knowledge base.\n\nFile size: ${(file.size / 1024).toFixed(1)} KB\nFile type: ${file.type || 'unknown'}`,
        }
        addDocument(newDoc)
        simulateUploadPipeline(id, updateDocumentStatus)
      })
    },
    [addDocument, updateDocumentStatus]
  )

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
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
        style={{ background: '#00000040' }}
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
          width: 440,
          background: '#0B132B',
          borderLeft: '1px solid #3A506B',
          boxShadow: '-20px 0 60px #00000060',
          animation: 'slideInRight 0.25s ease-out',
        }}
      >
        {/* Header */}
        <div
          className="px-4 py-3 flex items-center justify-between shrink-0"
          style={{ borderBottom: '1px solid #3A506B', background: '#1C2541' }}
        >
          <div>
            <div className="text-sm font-bold" style={{ color: '#e2e8f0', fontFamily: 'Inter, sans-serif' }}>
              Knowledge Hub
            </div>
            <div className="text-[10px]" style={{ color: '#8a9ab5', fontFamily: 'Roboto Mono, monospace' }}>
              {documents.filter((d) => d.indexStatus === 'vectorized').length} vectorized &nbsp;·&nbsp; {documents.length} total
            </div>
          </div>
          <button
            aria-label="Close Knowledge Hub"
            onClick={() => setKnowledgeDrawerOpen(false)}
            className="rounded p-1.5 transition-colors hover:bg-[#3A506B]/40 focus-visible:outline-2 focus-visible:outline-[#00A896]"
          >
            <XIcon size={16} style={{ color: '#8a9ab5' }} />
          </button>
        </div>

        {/* Upload zone */}
        <div className="px-4 py-3 shrink-0" style={{ borderBottom: '1px solid #3A506B' }}>
          <div
            {...getRootProps()}
            id="knowledge-upload-dropzone"
            className="rounded border-2 border-dashed px-4 py-5 text-center cursor-pointer transition-all focus-visible:outline-2 focus-visible:outline-[#00A896]"
            style={{
              borderColor: isDragActive ? '#00A896' : '#3A506B',
              background: isDragActive ? '#00A89610' : '#1C2541',
            }}
            tabIndex={0}
            role="button"
            aria-label="Drop files here or click to upload. Accepted: PDF, DOCX, TXT, CSV"
          >
            <input {...getInputProps()} />
            <UploadCloudIcon
              size={24}
              style={{ color: isDragActive ? '#00A896' : '#3A506B', margin: '0 auto 8px' }}
            />
            <div className="text-xs font-medium" style={{ color: isDragActive ? '#00A896' : '#8a9ab5', fontFamily: 'Inter, sans-serif' }}>
              {isDragActive ? 'Drop files here' : 'Drag & drop or click to upload'}
            </div>
            <div className="text-[10px] mt-1" style={{ color: '#3A506B', fontFamily: 'Roboto Mono, monospace' }}>
              PDF · DOCX · TXT · CSV
            </div>
          </div>
        </div>

        {/* Document table */}
        <div className="flex-1 overflow-y-auto scrollbar-thin px-4 py-3">
          <table className="w-full" style={{ borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ borderBottom: '1px solid #3A506B' }}>
                {['Document', 'Size', 'Imported', 'Status', 'Actions'].map((h) => (
                  <th
                    key={h}
                    className="pb-2 text-left text-[10px] uppercase tracking-wider"
                    style={{ color: '#3A506B', fontFamily: 'Roboto Mono, monospace' }}
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {documents.map((doc) => (
                <DocumentRow
                  key={doc.id}
                  doc={doc}
                  onPreview={(id) => setPreviewDocumentId(id)}
                  onDelete={(id) => deleteDocument(id)}
                />
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Preview Modal */}
      <PreviewModal doc={previewDoc} onClose={() => setPreviewDocumentId(null)} />
    </>
  )
}
