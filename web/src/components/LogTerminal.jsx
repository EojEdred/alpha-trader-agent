import { useEffect, useRef } from 'react'
import { useAlphaTrader } from '../context/WebSocketContext'

export default function LogTerminal() {
  const { logs } = useAlphaTrader()
  const bottomRef = useRef(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [logs])

  return (
    <div className="bg-panel border border-border rounded-xl h-[calc(100vh-140px)] flex flex-col overflow-hidden">
      <div className="flex items-center justify-between px-4 py-3 border-b border-border">
        <div className="flex items-center gap-2">
          <span className="text-xs font-bold uppercase tracking-wide text-dim">Live Logs</span>
          <span className="w-2 h-2 rounded-full bg-green animate-pulse-dot" />
        </div>
        <div className="text-xs text-dim">{logs.length} lines</div>
      </div>
      <div className="flex-1 overflow-y-auto p-4 font-mono text-xs leading-relaxed bg-bg">
        {logs.length === 0 && <span className="text-dim">Waiting for logs…</span>}
        {logs.map((line, i) => (
          <div key={i} className="break-words">
            <span className="text-dim">{line}</span>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>
    </div>
  )
}
