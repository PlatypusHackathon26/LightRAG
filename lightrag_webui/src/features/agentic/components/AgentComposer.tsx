import { useRef, useCallback, useState } from 'react'
import { SendIcon, PaperclipIcon } from 'lucide-react'

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
      style={{ borderTop: '1px solid #3A506B', background: '#0B132B' }}
    >
      <div
        className="flex items-end gap-2 rounded"
        style={{ background: '#1C2541', border: '1px solid #3A506B' }}
      >
        {/* Attachment */}
        <button
          aria-label="Attach file"
          className="p-2.5 rounded-l transition-colors hover:bg-[#3A506B]/40 focus-visible:outline-2 focus-visible:outline-[#00A896]"
          style={{ color: '#3A506B' }}
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
          className="flex-1 resize-none bg-transparent py-2.5 text-sm outline-none placeholder:text-[#3A506B] disabled:opacity-50"
          style={{
            color: '#e2e8f0',
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
          className="p-2.5 rounded-r transition-all focus-visible:outline-2 focus-visible:outline-[#00A896] disabled:opacity-40 disabled:cursor-not-allowed"
          style={{
            color: value.trim() ? '#00A896' : '#3A506B',
          }}
        >
          <SendIcon size={16} />
        </button>
      </div>

      <div
        className="text-[10px] text-center mt-1.5"
        style={{ color: '#3A506B', fontFamily: 'Roboto Mono, monospace' }}
      >
        Enter to send · Shift+Enter for newline · DEMO MODE
      </div>
    </div>
  )
}
