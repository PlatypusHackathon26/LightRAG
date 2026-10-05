import React from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { ChatMessage as ChatMessageType } from '../types/agentic'
import { FileTextIcon, UserIcon, BotIcon } from 'lucide-react'

export default function ChatMessage({ message }: { message: ChatMessageType }) {
  const isUser = message.role === 'user'
  const isSystem = message.role === 'system'

  if (isSystem) {
    return (
      <div className="flex justify-center my-1">
        <div
          className="text-[10px] rounded px-3 py-1"
          style={{ background: '#1C2541', color: '#8a9ab5', border: '1px solid #3A506B', fontFamily: 'Roboto Mono, monospace' }}
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
          background: isUser ? '#1C2541' : '#00A89620',
          border: `1px solid ${isUser ? '#3A506B' : '#00A896'}`,
        }}
      >
        {isUser ? (
          <UserIcon size={13} style={{ color: '#8a9ab5' }} />
        ) : (
          <BotIcon size={13} style={{ color: '#00A896' }} />
        )}
      </div>

      {/* Bubble */}
      <div className={`max-w-[78%] flex flex-col ${isUser ? 'items-end' : 'items-start'}`}>
        {/* Header */}
        <div className="flex items-center gap-2 mb-0.5">
          <span
            className="text-[10px] font-medium"
            style={{ color: '#64748b', fontFamily: 'Roboto Mono, monospace' }}
          >
            {message.timestamp}
          </span>
          <span
            className="text-[10px]"
            style={{ color: isUser ? '#8a9ab5' : '#00A896', fontFamily: 'Roboto Mono, monospace' }}
          >
            {isUser ? 'Operator' : 'AI Agent'}
          </span>
        </div>

        {/* Content */}
        <div
          className="rounded p-3 text-xs"
          style={{
            background: isUser ? '#1C2541' : '#0B132B',
            border: `1px solid ${isUser ? '#3A506B' : '#00A89630'}`,
            color: '#e2e8f0',
            fontFamily: 'Inter, sans-serif',
            lineHeight: 1.6,
          }}
        >
          {isUser ? (
            <span style={{ whiteSpace: 'pre-wrap' }}>{message.content}</span>
          ) : (
            <div
              className="prose prose-sm dark:prose-invert max-w-none"
              style={{
                // Override prose colors for industrial dark theme
                '--tw-prose-body': '#e2e8f0',
                '--tw-prose-headings': '#f1f5f9',
                '--tw-prose-bold': '#f1f5f9',
                '--tw-prose-bullets': '#3A506B',
                '--tw-prose-counters': '#8a9ab5',
                '--tw-prose-th-borders': '#3A506B',
                '--tw-prose-td-borders': '#3A506B',
                '--tw-prose-code': '#00A896',
                '--tw-prose-links': '#00A896',
                '--tw-prose-quotes': '#94a3b8',
                '--tw-prose-quote-borders': '#3A506B',
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
                            background: '#0B132B',
                            border: '1px solid #3A506B',
                            fontFamily: 'Roboto Mono, monospace',
                            fontSize: '11px',
                          }}
                        >
                          <code style={{ color: '#00A896' }} {...props}>{children}</code>
                        </pre>
                      )
                    }
                    return (
                      <code
                        className="rounded px-1 py-0.5"
                        style={{
                          background: '#1C2541',
                          color: '#00A896',
                          fontFamily: 'Roboto Mono, monospace',
                          fontSize: '11px',
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
                            fontSize: '11px',
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
                          background: '#1C2541',
                          color: '#8a9ab5',
                          padding: '4px 8px',
                          textAlign: 'left',
                          borderBottom: '1px solid #3A506B',
                          fontFamily: 'Roboto Mono, monospace',
                          fontSize: '10px',
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
                          borderBottom: '1px solid #3A506B20',
                          color: '#e2e8f0',
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

        {/* Citations */}
        {message.citations && message.citations.length > 0 && (
          <div className="flex flex-wrap gap-1.5 mt-1.5">
            {message.citations.map((c) => (
              <div
                key={c.id}
                className="flex items-center gap-1 rounded px-2 py-1"
                style={{
                  background: '#1C2541',
                  border: '1px solid #3A506B',
                }}
                title={c.excerpt}
              >
                <FileTextIcon size={10} style={{ color: '#00A896', flexShrink: 0 }} />
                <div className="leading-tight">
                  <div className="text-[10px] font-medium" style={{ color: '#94a3b8', fontFamily: 'Roboto Mono, monospace' }}>
                    {c.documentName}
                  </div>
                  {c.pages && (
                    <div className="text-[10px]" style={{ color: '#3A506B', fontFamily: 'Roboto Mono, monospace' }}>
                      Pages {c.pages}
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
