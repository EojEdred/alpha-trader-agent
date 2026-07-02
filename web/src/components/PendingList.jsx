import { useState } from 'react'
import { IconCheck, IconX, IconLoader2 } from '@tabler/icons-react'
import { useAlphaTrader } from '../context/WebSocketContext'
import StatusBadge from './StatusBadge'

export default function PendingList({ pending }) {
  const { sendCommand } = useAlphaTrader()
  const [acting, setActing] = useState({})

  const handleApprove = async (id) => {
    setActing((p) => ({ ...p, [id]: 'approve' }))
    try {
      await sendCommand('approve', id)
    } finally {
      setActing((p) => ({ ...p, [id]: null }))
    }
  }

  const handleReject = async (id) => {
    setActing((p) => ({ ...p, [id]: 'reject' }))
    try {
      await sendCommand('reject', id)
    } finally {
      setActing((p) => ({ ...p, [id]: null }))
    }
  }

  if (!pending || pending.length === 0) {
    return (
      <div className="bg-panel border border-border rounded-xl p-8 text-center text-dim text-sm">
        No pending confirmations
      </div>
    )
  }

  return (
    <div className="space-y-3">
      {pending.map((p) => (
        <div
          key={p.id}
          className="bg-panel border border-border rounded-xl p-4 flex flex-col md:flex-row md:items-center justify-between gap-4"
        >
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-3 mb-1">
              <span className="font-bold text-lg">{p.symbol}</span>
              <span className={`text-sm font-medium ${p.direction === 'long' ? 'text-green' : 'text-red'}`}>
                {p.direction}
              </span>
              <StatusBadge status={p.status} />
              <span className="text-xs text-dim">{p.venue}</span>
            </div>
            <div className="text-sm text-dim">
              size {p.size ?? '-'} • entry {p.entry_price?.toFixed(2)} • stop {p.stop_price?.toFixed(2)} • target {p.target_price?.toFixed(2)}
            </div>
            <div className="text-xs text-dim/60 font-mono mt-1 truncate">{p.id}</div>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <button
              onClick={() => handleApprove(p.id)}
              disabled={acting[p.id]}
              className="flex items-center gap-1.5 px-4 py-2 bg-green/10 hover:bg-green/20 text-green rounded-lg text-sm font-semibold transition-colors disabled:opacity-50"
            >
              {acting[p.id] === 'approve' ? <IconLoader2 className="w-4 h-4 animate-spin" /> : <IconCheck className="w-4 h-4" />}
              Approve
            </button>
            <button
              onClick={() => handleReject(p.id)}
              disabled={acting[p.id]}
              className="flex items-center gap-1.5 px-4 py-2 bg-red/10 hover:bg-red/20 text-red rounded-lg text-sm font-semibold transition-colors disabled:opacity-50"
            >
              {acting[p.id] === 'reject' ? <IconLoader2 className="w-4 h-4 animate-spin" /> : <IconX className="w-4 h-4" />}
              Reject
            </button>
          </div>
        </div>
      ))}
    </div>
  )
}
