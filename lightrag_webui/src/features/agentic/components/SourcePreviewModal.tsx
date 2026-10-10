/**
 * Preview of a knowledge document's original file: the file just dropped in (demo mode) or the
 * upload the gateway still holds (live, GET /agent/documents/{id}/file). PDFs open at the cited page.
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { pdfjs, Document, Page } from 'react-pdf'
import { FileTextIcon, LoaderIcon, XIcon } from 'lucide-react'
import { agentClient } from '../../../api/agent'
import type { KnowledgeDocument } from '../types/agentic'

// Bundled with the app (no CDN), so previews also work offline.
pdfjs.GlobalWorkerOptions.workerSrc = new URL('pdfjs-dist/build/pdf.worker.min.mjs', import.meta.url).toString()

type Kind = 'pdf' | 'image' | 'text' | 'other'

function kindOf(type: string, name: string): Kind {
  const ext = name.toLowerCase().split('.').pop() ?? ''
  if (type === 'application/pdf' || ext === 'pdf') return 'pdf'
  if (type.startsWith('image/') || ['png', 'jpg', 'jpeg', 'webp', 'gif', 'bmp'].includes(ext)) return 'image'
  if (type.startsWith('text/') || ['txt', 'md', 'csv'].includes(ext)) return 'text'
  return 'other'
}

const MUTED = { color: '#5B6575', fontSize: 13, fontFamily: 'Inter, sans-serif' }

function Loading({ label }: { label: string }) {
  return (
    <div className="flex items-center justify-center py-8">
      <LoaderIcon size={24} className="animate-spin" style={{ color: '#00A896' }} />
      <span className="ml-2" style={MUTED}>{label}</span>
    </div>
  )
}

function PdfView({ file, page }: { file: Blob; page?: number }) {
  const [numPages, setNumPages] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const scrolled = useRef(false)
  if (error) {
    return <div className="text-center py-8" style={{ ...MUTED, color: '#EF4444' }}>Không mở được PDF: {error}</div>
  }
  return (
    <Document
      file={file}
      onLoadSuccess={({ numPages: n }) => setNumPages(n)}
      onLoadError={(e) => setError(e.message)}
      loading={<Loading label="Đang mở PDF…" />}
    >
      {Array.from({ length: numPages }, (_, i) => i + 1).map((n) => (
        <div
          key={n}
          className="mb-4"
          style={n === page ? { outline: '2px solid #00A896', outlineOffset: 2 } : undefined}
        >
          <Page
            pageNumber={n}
            width={800}
            renderTextLayer={false}
            renderAnnotationLayer={false}
            inputRef={n === page ? (el) => {
              if (el && !scrolled.current) {
                scrolled.current = true
                el.scrollIntoView({ block: 'start' })
              }
            } : undefined}
          />
        </div>
      ))}
    </Document>
  )
}

function FileView({ file, name, page }: { file: Blob; name: string; page?: number }) {
  const kind = kindOf(file.type, name)
  const url = useMemo(() => (kind === 'image' || kind === 'other' ? URL.createObjectURL(file) : null), [file, kind])
  useEffect(() => () => {
    if (url) URL.revokeObjectURL(url)
  }, [url])
  const [text, setText] = useState<string | null>(null)
  useEffect(() => {
    if (kind !== 'text') return
    let cancelled = false
    file.text().then((t) => !cancelled && setText(t))
    return () => {
      cancelled = true
    }
  }, [file, kind])

  if (kind === 'pdf') return <PdfView file={file} page={page} />
  if (kind === 'text') {
    return (
      <pre className="leading-relaxed whitespace-pre-wrap" style={{ fontSize: 13, color: '#172033', fontFamily: 'Roboto Mono, monospace' }}>
        {text ?? ''}
      </pre>
    )
  }
  if (!url) return null
  if (kind === 'image') return <img src={url} alt={name} style={{ maxWidth: '100%', margin: '0 auto' }} />
  return (
    <div className="text-center py-8" style={MUTED}>
      <FileTextIcon size={32} style={{ color: '#00A896', margin: '0 auto 8px' }} />
      <p>Trình duyệt không xem trực tiếp được định dạng này.</p>
      <a href={url} download={name} style={{ color: '#00A896' }}>Tải file gốc</a>
    </div>
  )
}

function Fallback({ doc, reason }: { doc: KnowledgeDocument; reason: string }) {
  return (
    <div className="text-center py-8" style={MUTED}>
      <FileTextIcon size={32} style={{ color: '#00A896', margin: '0 auto 8px' }} />
      <p>{reason}</p>
      {doc.extractedText && (
        <details className="mt-4 text-left">
          <summary className="cursor-pointer" style={{ color: '#00A896' }}>Xem nội dung đã trích</summary>
          <pre
            className="mt-2 p-3 rounded leading-relaxed whitespace-pre-wrap"
            style={{ fontSize: 12, color: '#172033', fontFamily: 'Roboto Mono, monospace', background: '#F0F4F8', border: '1px solid #D9E1E8' }}
          >
            {doc.extractedText}
          </pre>
        </details>
      )}
    </div>
  )
}

function PreviewBody({ doc, page }: { doc: KnowledgeDocument; page?: number }) {
  const [state, setState] = useState<{ file?: Blob; error?: string }>(() => (doc.file ? { file: doc.file } : {}))
  useEffect(() => {
    if (doc.file || !agentClient.live) return
    let cancelled = false
    agentClient.fetchDocumentFile(doc.id).then(
      (file) => !cancelled && setState({ file }),
      (e: Error) => !cancelled && setState({ error: e.message })
    )
    return () => {
      cancelled = true
    }
  }, [doc.id, doc.file])

  if (state.file) return <FileView file={state.file} name={doc.file?.name ?? doc.name} page={page} />
  if (state.error) {
    const missing = /\b404\b/.test(state.error)
    return <Fallback doc={doc} reason={missing ? 'Máy chủ không còn giữ file gốc của tài liệu này.' : `Không tải được file gốc (${state.error}).`} />
  }
  if (agentClient.live && !doc.file) return <Loading label="Đang tải file gốc…" />
  return <Fallback doc={doc} reason="Dữ liệu mẫu: không có file gốc để xem." />
}

export default function SourcePreviewModal({
  doc,
  page,
  onClose,
}: {
  doc: KnowledgeDocument | null
  page?: number
  onClose: () => void
}) {
  useEffect(() => {
    if (!doc) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [doc, onClose])

  if (!doc) return null
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ background: 'rgba(15,23,42,0.5)', backdropFilter: 'blur(4px)' }}
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label={`Preview: ${doc.name}`}
    >
      <div
        className="rounded overflow-hidden flex flex-col"
        style={{
          maxWidth: 900,
          width: '95vw',
          height: '90vh',
          background: '#FFFFFF',
          border: '1px solid #D9E1E8',
          boxShadow: '0 20px 60px rgba(0,0,0,0.25)',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-4 py-3" style={{ borderBottom: '1px solid #D9E1E8' }}>
          <div className="flex items-center gap-2 min-w-0">
            <FileTextIcon size={14} style={{ color: '#00A896', flexShrink: 0 }} />
            <span className="font-semibold truncate" style={{ fontSize: 15, color: '#172033', fontFamily: 'Inter, sans-serif' }}>
              {doc.name}
            </span>
            {page && (
              <span style={{ fontSize: 12, color: '#5B6575', fontFamily: 'Roboto Mono, monospace', flexShrink: 0 }}>
                · trang {page}
              </span>
            )}
          </div>
          <button
            aria-label="Close preview"
            onClick={onClose}
            className="rounded p-1 hover:bg-[#F0F4F8] transition-colors focus-visible:outline-2 focus-visible:outline-[#00A896]"
          >
            <XIcon size={14} style={{ color: '#5B6575' }} />
          </button>
        </div>
        <div className="flex-1 overflow-auto p-4" style={{ background: '#F8FAFC' }}>
          {/* keyed: a new document starts from a clean load state */}
          <PreviewBody key={`${doc.id}:${page ?? ''}`} doc={doc} page={page} />
        </div>
      </div>
    </div>
  )
}
