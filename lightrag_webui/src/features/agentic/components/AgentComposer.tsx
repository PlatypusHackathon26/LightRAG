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
    <div className="shrink-0 px-4 md:px-8 pb-4 pt-2" style={{ borderTop: '1px solid #1E293B', background: '#0F172A' }}>
      <div
        className="flex items-end gap-2 rounded-2xl px-2 py-2 transition focus-within:border-[#06B6D4]"
        style={{ background: '#0F172A', border: '1px solid #334155' }}
      >
        {/* Attachment */}
        <button
          aria-label="Attach file"
          className="p-1.5 rounded-lg transition-colors hover:bg-[#1E293B] focus-visible:outline-2 focus-visible:outline-[#06B6D4]"
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
          placeholder="Hỏi Agent về sự cố máy... (Enter gửi · Shift+Enter xuống dòng)"
          rows={1}
          className="flex-1 resize-none bg-transparent py-1.5 outline-none disabled:opacity-50"
          style={{
            fontSize: 14,
            color: '#F1F5F9',
            fontFamily: 'Inter, sans-serif',
            lineHeight: 1.5,
            maxHeight: 140,
            minHeight: 32,
          }}
          aria-label="Nội dung tin nhắn. Enter để gửi, Shift+Enter để xuống dòng."
        />

        {/* Send */}
        <button
          id="agent-send-button"
          aria-label="Gửi tin nhắn"
          onClick={handleSend}
          disabled={!value.trim() || disabled}
          className="flex items-center justify-center shrink-0 rounded-xl font-bold transition hover:bg-[#DC2626] focus-visible:outline-2 focus-visible:outline-[#F87171] disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:bg-[#E60012]"
          style={{ width: 36, height: 36, background: '#E60012', color: '#FFFFFF' }}
        >
          <SendIcon size={15} />
        </button>
      </div>

      <p className="text-center mt-1.5" style={{ fontSize: 10, color: '#475569' }}>
        Agent trả lời theo tài liệu trong kho tri thức · Lệnh tới máy cần kỹ sư duyệt
        {agentConfig.live ? '' : ' · DEMO (dữ liệu mẫu)'}
      </p>
    </div>
  )
}
