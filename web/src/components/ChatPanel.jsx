import { useRef, useEffect, useState } from 'react'
import { IconSend, IconLoader2 } from '@tabler/icons-react'
import { useAlphaTrader } from '../context/WebSocketContext'
import { cn, formatTime } from '../lib/utils'

const quickCommands = ['status', 'positions', 'risk', 'pause', 'start', 'help']

export default function ChatPanel() {
  const { chatMessages, sendCommand } = useAlphaTrader()
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const scrollRef = useRef(null)

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [chatMessages])

  const handleSend = async () => {
    if (!input.trim() || loading) return
    const msg = input.trim()
    setInput('')
    setLoading(true)
    try {
      await sendCommand('chat', msg)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex flex-col h-[calc(100vh-140px)] bg-panel border border-border rounded-xl overflow-hidden">
      <div ref={scrollRef} className="flex-1 overflow-y-auto p-4 space-y-4">
        {chatMessages.length === 0 && (
          <div className="text-center text-dim text-sm py-10">
            Ask Dexter for status, trades, or type a command.
          </div>
        )}
        {chatMessages.map((msg, idx) => (
          <div key={idx} className={cn('flex flex-col', msg.role === 'user' ? 'items-end' : 'items-start')}>
            <div className="text-[10px] text-dim mb-1">{msg.role === 'user' ? 'You' : 'Dexter'} • {formatTime(msg.time)}</div>
            <div
              className={cn(
                'max-w-[80%] px-4 py-2.5 rounded-2xl text-sm whitespace-pre-wrap',
                msg.role === 'user'
                  ? 'bg-blue/15 text-blue border border-blue/20 rounded-tr-sm'
                  : 'bg-panel-hover text-text border border-border rounded-tl-sm'
              )}
            >
              {msg.text}
            </div>
          </div>
        ))}
        {loading && (
          <div className="flex flex-col items-start">
            <div className="text-[10px] text-dim mb-1">Dexter</div>
            <div className="bg-panel-hover border border-border rounded-2xl rounded-tl-sm px-4 py-2.5 text-sm text-dim flex items-center gap-2">
              <IconLoader2 className="w-4 h-4 animate-spin" />
              Thinking…
            </div>
          </div>
        )}
      </div>

      <div className="border-t border-border p-4">
        <div className="flex gap-2">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleSend()}
            placeholder="Type a command or question…"
            className="flex-1 bg-bg border border-border rounded-lg px-4 py-2.5 text-sm text-text placeholder:text-dim/50 focus:outline-none focus:border-blue focus:ring-1 focus:ring-blue"
          />
          <button
            onClick={handleSend}
            disabled={loading || !input.trim()}
            className="bg-blue hover:bg-blue/90 disabled:opacity-50 text-white px-4 py-2.5 rounded-lg font-semibold transition-colors flex items-center gap-2"
          >
            {loading ? <IconLoader2 className="w-4 h-4 animate-spin" /> : <IconSend className="w-4 h-4" />}
            Send
          </button>
        </div>
        <div className="flex flex-wrap gap-2 mt-3">
          {quickCommands.map((cmd) => (
            <button
              key={cmd}
              onClick={() => setInput(cmd)}
              className="px-2.5 py-1 rounded-full bg-bg border border-border text-xs text-dim hover:text-text hover:border-border/80 transition-colors"
            >
              {cmd}
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}
