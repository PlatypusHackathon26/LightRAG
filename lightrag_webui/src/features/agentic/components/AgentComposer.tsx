import { useRef, useCallback, useState } from 'react'
import { SendIcon, PaperclipIcon } from 'lucide-react'
import { agentConfig } from '../agentConfig'

interface AgentComposerProps {
  onSend: (message: string) => void
  disabled?: boolean
}

export default function AgentComposer({ onSend, disabled }: AgentComposerProps) {
  const [value, setValue] = useState('')
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const handleSend = useCallback(() => {
    const trimmed = value.trim()
    if (!trimmed || disabled) return
    onSend(trimmed)
    setValue('')
    // Reset height
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
    }
  }, [value, disabled, onSend])

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const handleInput = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setValue(e.target.value)
    // Auto-expand
    const el = textareaRef.current
    if (el) {
      el.style.height = 'auto'
      el.style.height = Math.min(el.scrollHeight, 140) + 'px'
    }
  }

  return (
    <div
      className="shrink-0 px-4 py-3"
      style={{ borderTop: '1px solid #263347', background: '#0B1220' }}
    >
      <div
        className="flex items-end gap-2 rounded"
        style={{ background: '#0F172A', border: '1px solid #334155', borderRadius: 16 }}
      >
        {/* Attachment */}
        <button
          aria-label="Attach file"
          className="p-2.5 rounded-l transition-colors hover:bg-[#1E293B] focus-visible:outline-2 focus-visible:outline-[#06B6D4]"
          style={{ color: '#64748B' }}
        >
          <PaperclipIcon size={16} />
        </button>

        {/* Textarea */}
        <textarea
          id="agent-composer-input"
          ref={textareaRef}
          value={value}
          onChange={handleInput}
          onKeyDown={handleKeyDown}
          disabled={disabled}
          placeholder="Chat với Agent hoặc ra lệnh..."
          rows={1}
          className="flex-1 resize-none bg-transparent py-2.5 outline-none disabled:opacity-50"
          style={{
            fontSize: 15,
            color: '#E2E8F0',
            fontFamily: 'Inter, sans-serif',
            lineHeight: 1.5,
            maxHeight: 140,
            minHeight: 36,
          }}
          aria-label="Message input. Press Enter to send, Shift+Enter for newline."
        />

        {/* Send */}
        <button
          id="agent-send-button"
          aria-label="Send message"
          onClick={handleSend}
          disabled={!value.trim() || disabled}
          className="p-2.5 rounded-r transition-all focus-visible:outline-2 focus-visible:outline-[#06B6D4] disabled:opacity-40 disabled:cursor-not-allowed"
          style={{
            color: value.trim() ? '#E60012' : '#64748B',
          }}
        >
          <SendIcon size={16} />
        </button>
      </div>

      <div
        className="text-center mt-1.5"
        style={{ fontSize: 11, color: '#64748B', fontFamily: 'Roboto Mono, monospace' }}
      >
        Enter to send · Shift+Enter for newline · {agentConfig.live ? 'LIVE · Agent Gateway' : 'DEMO MODE (mock data)'}
      </div>
    </div>
  )
}
