import React, { useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { ChatMessage as ChatMessageType } from '../types/agentic'
import { useAgenticStore } from '../stores/agenticStore'
import SourcePreviewModal from './SourcePreviewModal'
import { firstPage } from '../format'
import { FileTextIcon, UserIcon, BotIcon, ChevronDownIcon, XIcon, EyeIcon } from 'lucide-react'

export default function ChatMessage({ message }: { message: ChatMessageType }) {
  const isUser = message.role === 'user'
  const isSystem = message.role === 'system'
  const [showSources, setShowSources] = useState(false)
  const [preview, setPreview] = useState<{ docId: string; page?: number } | null>(null)
  const { documents } = useAgenticStore()

  const previewDoc = documents.find((d) => d.id === preview?.docId) ?? null

  if (isSystem) {
    return (
      <div className="flex justify-center my-1">
        <div
          className="rounded px-3 py-1"
          style={{ fontSize: 11, background: '#2A1215', color: '#FECACA', border: '1px solid #7F1D1D', fontFamily: 'Roboto Mono, monospace' }}
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
          background: isUser ? '#4F46E5' : '#0891B2',
          border: `1px solid ${isUser ? '#6366F1' : '#06B6D4'}`,
        }}
      >
        {isUser ? (
          <UserIcon size={13} style={{ color: '#FFFFFF' }} />
        ) : (
          <BotIcon size={13} style={{ color: '#FFFFFF' }} />
        )}
      </div>

      {/* Bubble */}
      <div className={`max-w-[78%] flex flex-col ${isUser ? 'items-end' : 'items-start'}`}>
        {/* Header */}
        <div className="flex items-center gap-2 mb-0.5">
          <span
            className="font-medium"
            style={{ fontSize: 11, color: '#94A3B8', fontFamily: 'Roboto Mono, monospace' }}
          >
            {message.timestamp}
          </span>
          <span
            style={{ fontSize: 11, color: isUser ? '#A5B4FC' : '#22D3EE', fontFamily: 'Roboto Mono, monospace', fontWeight: 700 }}
          >
            {isUser ? 'Operator' : 'AI Agent'}
          </span>
        </div>

        {/* Content */}
        <div
          className="rounded-2xl p-3"
          style={{
            fontSize: 14,
            background: isUser ? '#4F46E5' : '#1E293B',
            border: `1px solid ${isUser ? '#4F46E5' : '#334155'}`,
            color: isUser ? '#FFFFFF' : '#E2E8F0',
            fontFamily: 'Inter, sans-serif',
            lineHeight: 1.65,
            boxShadow: 'none',
          }}
        >
          {isUser ? (
            <span style={{ whiteSpace: 'pre-wrap' }}>{message.content}</span>
          ) : (
            <div
              className="prose prose-sm max-w-none"
              style={{
                // Override prose colors for industrial light theme
                '--tw-prose-body': '#E2E8F0',
                '--tw-prose-headings': '#F1F5F9',
                '--tw-prose-bold': '#E2E8F0',
                '--tw-prose-bullets': '#94A3B8',
                '--tw-prose-counters': '#94A3B8',
                '--tw-prose-th-borders': '#263347',
                '--tw-prose-td-borders': '#263347',
                '--tw-prose-code': '#06B6D4',
                '--tw-prose-links': '#06B6D4',
                '--tw-prose-quotes': '#94A3B8',
                '--tw-prose-quote-borders': '#263347',
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
                            background: '#0F172A',
                            border: '1px solid #263347',
                            fontFamily: 'Roboto Mono, monospace',
                            fontSize: '12px',
                          }}
                        >
                          <code style={{ color: '#22D3EE' }} {...props}>{children}</code>
                        </pre>
                      )
                    }
                    return (
                      <code
                        className="rounded px-1 py-0.5"
                        style={{
                          background: '#083344',
                          color: '#22D3EE',
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
                          background: '#1E293B',
                          color: '#94A3B8',
                          padding: '4px 8px',
                          textAlign: 'left',
                          borderBottom: '1px solid #263347',
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
                          borderBottom: '1px solid #26334720',
                          color: '#E2E8F0',
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
              className="flex items-center gap-1.5 rounded px-2.5 py-1 transition-colors hover:bg-[#083344] focus-visible:outline-2 focus-visible:outline-[#06B6D4]"
              style={{
                background: '#1E293B',
                border: '1px solid #334155',
                boxShadow: 'none',
              }}
            >
              <FileTextIcon size={12} style={{ color: '#06B6D4', flexShrink: 0 }} />
              <span
                className="font-medium"
                style={{ fontSize: 12, color: '#94A3B8', fontFamily: 'Roboto Mono, monospace' }}
              >
                Nguồn tài liệu ({message.citations.length})
              </span>
              <ChevronDownIcon
                size={12}
                style={{ color: '#94A3B8', transition: 'transform 0.2s', transform: showSources ? 'rotate(180deg)' : 'rotate(0deg)' }}
              />
            </button>

            {/* Citations Panel */}
            {showSources && (
              <div
                className="mt-2 rounded overflow-hidden"
                style={{
                  background: '#1E293B',
                  border: '1px solid #334155',
                  boxShadow: '0 4px 16px rgba(0,0,0,0.35)',
                }}
              >
                <div className="px-3 py-2" style={{ borderBottom: '1px solid #263347', background: '#111A2C' }}>
                  <div className="flex items-center justify-between">
                    <span
                      className="font-medium"
                      style={{ fontSize: 12, color: '#94A3B8', fontFamily: 'Roboto Mono, monospace' }}
                    >
                      Tài liệu tham khảo
                    </span>
                    <button
                      onClick={() => setShowSources(false)}
                      className="rounded p-0.5 hover:bg-[#1E293B] transition-colors"
                    >
                      <XIcon size={12} style={{ color: '#94A3B8' }} />
                    </button>
                  </div>
                </div>
                <div className="p-2 space-y-1.5 max-h-48 overflow-y-auto">
                  {message.citations.map((c) => {
                    const doc = documents.find((d) => d.name === c.documentName)
                    return (
                      <div
                        key={c.id}
                        className="flex items-start gap-2 rounded px-2 py-1.5 transition-colors hover:bg-[#111A2C]"
                        style={{ border: '1px solid #263347' }}
                        title={c.excerpt}
                      >
                        <FileTextIcon size={11} style={{ color: '#06B6D4', flexShrink: 0, marginTop: 2 }} />
                        <div className="flex-1 min-w-0">
                          <div className="font-medium truncate" style={{ fontSize: 12, color: '#E2E8F0', fontFamily: 'Inter, sans-serif' }}>
                            {c.documentName}
                          </div>
                          {c.pages && (
                            <div style={{ fontSize: 11, color: '#94A3B8', fontFamily: 'Roboto Mono, monospace' }}>
                              Trang {c.pages}
                            </div>
                          )}
                        </div>
                        {doc && (
                          <button
                            onClick={() => setPreview({ docId: doc.id, page: firstPage(c.pages) })}
                            className="rounded p-1 transition-colors hover:bg-[#083344] focus-visible:outline-2 focus-visible:outline-[#06B6D4]"
                            title="Xem file nguồn"
                            style={{ flexShrink: 0 }}
                          >
                            <EyeIcon size={12} style={{ color: '#06B6D4' }} />
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
      <SourcePreviewModal doc={previewDoc} page={preview?.page} onClose={() => setPreview(null)} />
    </div>
  )
}
