import React, { useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { ChatMessage as ChatMessageType } from '../types/agentic'
import { useAgenticStore } from '../stores/agenticStore'
import { pdfjs, Document, Page } from 'react-pdf'
import { FileTextIcon, UserIcon, BotIcon, ChevronDownIcon, XIcon, EyeIcon, LoaderIcon } from 'lucide-react'

// Set up PDF.js worker
pdfjs.GlobalWorkerOptions.workerSrc = `//unpkg.com/pdfjs-dist@${pdfjs.version}/build/pdf.worker.min.mjs`

function CitationPreviewModal({ doc, onClose }: { doc: any; onClose: () => void }) {
  const [numPages, setNumPages] = useState<number | null>(null)
  const [pdfError, setPdfError] = useState<string | null>(null)

  if (!doc) return null

  const handleLoadSuccess = ({ numPages: nextNumPages }: { numPages: number }) => {
    setNumPages(nextNumPages)
  }

  const handleLoadError = (error: Error) => {
    setPdfError(error.message)
  }

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
          maxHeight: '90vh',
          background: '#FFFFFF',
          border: '1px solid #D9E1E8',
          boxShadow: '0 20px 60px rgba(0,0,0,0.25)',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div
          className="flex items-center justify-between px-4 py-3"
          style={{ borderBottom: '1px solid #D9E1E8' }}
        >
          <div className="flex items-center gap-2">
            <FileTextIcon size={14} style={{ color: '#00A896' }} />
            <span className="font-semibold" style={{ fontSize: 15, color: '#172033', fontFamily: 'Inter, sans-serif' }}>
              {doc.name}
            </span>
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
          {doc.file ? (
            <Document
              file={doc.file}
              onLoadSuccess={handleLoadSuccess}
              onLoadError={handleLoadError}
              loading={
                <div className="flex items-center justify-center py-8">
                  <LoaderIcon size={24} className="animate-spin" style={{ color: '#00A896' }} />
                  <span className="ml-2" style={{ fontSize: 13, color: '#5B6575', fontFamily: 'Inter, sans-serif' }}>
                    Loading PDF...
                  </span>
                </div>
              }
            >
              {pdfError ? (
                <div className="text-center py-8" style={{ color: '#EF4444', fontSize: 13, fontFamily: 'Inter, sans-serif' }}>
                  Failed to load PDF: {pdfError}
                </div>
              ) : (
                Array.from(new Array(numPages ?? 0), (_, index) => (
                  <div key={`page_${index + 1}`} className="mb-4">
                    <Page
                      pageNumber={index + 1}
                      width={800}
                      renderTextLayer={false}
                      renderAnnotationLayer={false}
                    />
                  </div>
                ))
              )}
            </Document>
          ) : (
            <div className="text-center py-8" style={{ color: '#5B6575', fontSize: 13, fontFamily: 'Inter, sans-serif' }}>
              <FileTextIcon size={32} style={{ color: '#00A896', marginBottom: 8 }} />
              <p>Document preview requires the original file.</p>
              <p style={{ fontSize: 11, marginTop: 4 }}>This is mock data with extracted text only.</p>
              <details className="mt-4 text-left">
                <summary className="cursor-pointer" style={{ color: '#00A896' }}>
                  View extracted text
                </summary>
                <pre
                  className="mt-2 p-3 rounded leading-relaxed whitespace-pre-wrap"
                  style={{ fontSize: 12, color: '#172033', fontFamily: 'Roboto Mono, monospace', background: '#F0F4F8', border: '1px solid #D9E1E8' }}
                >
                  {doc.extractedText ?? '(No extracted text available)'}
                </pre>
              </details>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export default function ChatMessage({ message }: { message: ChatMessageType }) {
  const isUser = message.role === 'user'
  const isSystem = message.role === 'system'
  const [showSources, setShowSources] = useState(false)
  const [previewDocId, setPreviewDocId] = useState<string | null>(null)
  const { documents } = useAgenticStore()

  const previewDoc = documents.find((d) => d.id === previewDocId) ?? null

  const handlePreviewCitation = (citationId: string) => {
    setPreviewDocId(citationId)
  }

  if (isSystem) {
    return (
      <div className="flex justify-center my-1">
        <div
          className="rounded px-3 py-1"
          style={{ fontSize: 11, background: '#F0F4F8', color: '#5B6575', border: '1px solid #D9E1E8', fontFamily: 'Roboto Mono, monospace' }}
        >
          {message.content}
        </div>
      </div>
    )
  }

  return (
    <div className={`flex gap-2.5 px-4 py-2 ${isUser ? 'flex-row-reverse' : 'flex-row'}`}>
      {/* Avatar */}
      <div
        className="flex items-center justify-center rounded-full shrink-0 mt-0.5"
        style={{
          width: 28,
          height: 28,
          background: isUser ? '#F0F4F8' : '#EBF5F4',
          border: `1px solid ${isUser ? '#D9E1E8' : '#00A89650'}`,
        }}
      >
        {isUser ? (
          <UserIcon size={13} style={{ color: '#5B6575' }} />
        ) : (
          <BotIcon size={13} style={{ color: '#00A896' }} />
        )}
      </div>

      {/* Bubble */}
      <div className={`max-w-[78%] flex flex-col ${isUser ? 'items-end' : 'items-start'}`}>
        {/* Header */}
        <div className="flex items-center gap-2 mb-0.5">
          <span
            className="font-medium"
            style={{ fontSize: 11, color: '#5B6575', fontFamily: 'Roboto Mono, monospace' }}
          >
            {message.timestamp}
          </span>
          <span
            style={{ fontSize: 11, color: isUser ? '#5B6575' : '#00A896', fontFamily: 'Roboto Mono, monospace' }}
          >
            {isUser ? 'Operator' : 'AI Agent'}
          </span>
        </div>

        {/* Content */}
        <div
          className="rounded p-3"
          style={{
            fontSize: 14,
            background: isUser ? '#EEF2F7' : '#FFFFFF',
            border: `1px solid ${isUser ? '#D9E1E8' : '#D9E1E8'}`,
            color: '#172033',
            fontFamily: 'Inter, sans-serif',
            lineHeight: 1.65,
            boxShadow: isUser ? 'none' : '0 1px 4px rgba(0,0,0,0.06)',
          }}
        >
          {isUser ? (
            <span style={{ whiteSpace: 'pre-wrap' }}>{message.content}</span>
          ) : (
            <div
              className="prose prose-sm max-w-none"
              style={{
                // Override prose colors for industrial light theme
                '--tw-prose-body': '#172033',
                '--tw-prose-headings': '#0F172A',
                '--tw-prose-bold': '#172033',
                '--tw-prose-bullets': '#5B6575',
                '--tw-prose-counters': '#5B6575',
                '--tw-prose-th-borders': '#D9E1E8',
                '--tw-prose-td-borders': '#D9E1E8',
                '--tw-prose-code': '#00A896',
                '--tw-prose-links': '#00A896',
                '--tw-prose-quotes': '#5B6575',
                '--tw-prose-quote-borders': '#D9E1E8',
              } as React.CSSProperties}
            >
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{
                  code({ children, className, ...props }) {
                    const isBlock = className?.includes('language-')
                    if (isBlock) {
                      return (
                        <pre
                          className="rounded p-2 overflow-x-auto"
                          style={{
                            background: '#F0F4F8',
                            border: '1px solid #D9E1E8',
                            fontFamily: 'Roboto Mono, monospace',
                            fontSize: '12px',
                          }}
                        >
                          <code style={{ color: '#007A6C' }} {...props}>{children}</code>
                        </pre>
                      )
                    }
                    return (
                      <code
                        className="rounded px-1 py-0.5"
                        style={{
                          background: '#EBF5F4',
                          color: '#007A6C',
                          fontFamily: 'Roboto Mono, monospace',
                          fontSize: '12px',
                        }}
                        {...props}
                      >
                        {children}
                      </code>
                    )
                  },
                  table({ children }) {
                    return (
                      <div className="overflow-x-auto">
                        <table
                          style={{
                            width: '100%',
                            borderCollapse: 'collapse',
                            fontFamily: 'Roboto Mono, monospace',
                            fontSize: '12px',
                          }}
                        >
                          {children}
                        </table>
                      </div>
                    )
                  },
                  th({ children }) {
                    return (
                      <th
                        style={{
                          background: '#F0F4F8',
                          color: '#5B6575',
                          padding: '4px 8px',
                          textAlign: 'left',
                          borderBottom: '1px solid #D9E1E8',
                          fontFamily: 'Roboto Mono, monospace',
                          fontSize: '11px',
                          textTransform: 'uppercase',
                          letterSpacing: '0.05em',
                        }}
                      >
                        {children}
                      </th>
                    )
                  },
                  td({ children }) {
                    return (
                      <td
                        style={{
                          padding: '4px 8px',
                          borderBottom: '1px solid #D9E1E820',
                          color: '#172033',
                          verticalAlign: 'top',
                        }}
                      >
                        {children}
                      </td>
                    )
                  },
                }}
              >
                {message.content}
              </ReactMarkdown>
            </div>
          )}
        </div>

        {/* Source Button */}
        {message.citations && message.citations.length > 0 && !isUser && (
          <div className="mt-1.5">
            <button
              onClick={() => setShowSources(!showSources)}
              className="flex items-center gap-1.5 rounded px-2.5 py-1 transition-colors hover:bg-[#EBF5F4] focus-visible:outline-2 focus-visible:outline-[#00A896]"
              style={{
                background: '#FFFFFF',
                border: '1px solid #D9E1E8',
                boxShadow: '0 1px 2px rgba(0,0,0,0.04)',
              }}
            >
              <FileTextIcon size={12} style={{ color: '#00A896', flexShrink: 0 }} />
              <span
                className="font-medium"
                style={{ fontSize: 12, color: '#5B6575', fontFamily: 'Roboto Mono, monospace' }}
              >
                Nguồn tài liệu ({message.citations.length})
              </span>
              <ChevronDownIcon
                size={12}
                style={{ color: '#5B6575', transition: 'transform 0.2s', transform: showSources ? 'rotate(180deg)' : 'rotate(0deg)' }}
              />
            </button>

            {/* Citations Panel */}
            {showSources && (
              <div
                className="mt-2 rounded overflow-hidden"
                style={{
                  background: '#FFFFFF',
                  border: '1px solid #D9E1E8',
                  boxShadow: '0 2px 8px rgba(0,0,0,0.08)',
                }}
              >
                <div className="px-3 py-2" style={{ borderBottom: '1px solid #D9E1E8', background: '#F8FAFC' }}>
                  <div className="flex items-center justify-between">
                    <span
                      className="font-medium"
                      style={{ fontSize: 12, color: '#5B6575', fontFamily: 'Roboto Mono, monospace' }}
                    >
                      Tài liệu tham khảo
                    </span>
                    <button
                      onClick={() => setShowSources(false)}
                      className="rounded p-0.5 hover:bg-[#EEF2F7] transition-colors"
                    >
                      <XIcon size={12} style={{ color: '#5B6575' }} />
                    </button>
                  </div>
                </div>
                <div className="p-2 space-y-1.5 max-h-48 overflow-y-auto">
                  {message.citations.map((c) => {
                    const doc = documents.find((d) => d.name === c.documentName)
                    return (
                      <div
                        key={c.id}
                        className="flex items-start gap-2 rounded px-2 py-1.5 transition-colors hover:bg-[#F8FAFC]"
                        style={{ border: '1px solid #D9E1E8' }}
                        title={c.excerpt}
                      >
                        <FileTextIcon size={11} style={{ color: '#00A896', flexShrink: 0, marginTop: 2 }} />
                        <div className="flex-1 min-w-0">
                          <div className="font-medium truncate" style={{ fontSize: 12, color: '#172033', fontFamily: 'Inter, sans-serif' }}>
                            {c.documentName}
                          </div>
                          {c.pages && (
                            <div style={{ fontSize: 11, color: '#5B6575', fontFamily: 'Roboto Mono, monospace' }}>
                              Trang {c.pages}
                            </div>
                          )}
                        </div>
                        {doc && (
                          <button
                            onClick={() => handlePreviewCitation(doc.id)}
                            className="rounded p-1 transition-colors hover:bg-[#EBF5F4] focus-visible:outline-2 focus-visible:outline-[#00A896]"
                            title="Xem file nguồn"
                            style={{ flexShrink: 0 }}
                          >
                            <EyeIcon size={12} style={{ color: '#00A896' }} />
                          </button>
                        )}
                      </div>
                    )
                  })}
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Citation Preview Modal */}
      <CitationPreviewModal doc={previewDoc} onClose={() => setPreviewDocId(null)} />
    </div>
  )
}
