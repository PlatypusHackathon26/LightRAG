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

        {/* Citations */}
        {message.citations && message.citations.length > 0 && (
          <div className="flex flex-wrap gap-1.5 mt-1.5">
            {message.citations.map((c) => (
              <div
                key={c.id}
                className="flex items-center gap-1 rounded px-2 py-1"
                style={{
                  background: '#FFFFFF',
                  border: '1px solid #D9E1E8',
                  boxShadow: '0 1px 2px rgba(0,0,0,0.04)',
                }}
                title={c.excerpt}
              >
                <FileTextIcon size={10} style={{ color: '#00A896', flexShrink: 0 }} />
                <div className="leading-tight">
                  <div className="font-medium" style={{ fontSize: 11, color: '#5B6575', fontFamily: 'Roboto Mono, monospace' }}>
                    {c.documentName}
                  </div>
                  {c.pages && (
                    <div style={{ fontSize: 10, color: '#5B6575', fontFamily: 'Roboto Mono, monospace' }}>
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
