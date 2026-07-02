import { IconRobot, IconClock } from '@tabler/icons-react'
import { formatTime, statusColor, cn } from '../lib/utils'

export default function AgentGrid({ agents, compact = false }) {
  if (!agents || agents.length === 0) {
    return (
      <div className="bg-panel border border-border rounded-xl p-8 text-center text-dim text-sm">
        No agents registered
      </div>
    )
  }

  return (
    <div className={cn('grid gap-3', compact ? 'grid-cols-2 md:grid-cols-3 lg:grid-cols-4' : 'grid-cols-2 md:grid-cols-3 lg:grid-cols-5')}>
      {agents.map((a) => {
        const color = statusColor(a.status)
        return (
          <div
            key={a.name}
            className="bg-panel border border-border rounded-xl p-4 hover:border-border/80 transition-colors"
          >
            <div className="flex items-start justify-between mb-2">
              <div className="flex items-center gap-2">
                <div className={cn('p-1.5 rounded-md', color === 'green' ? 'bg-green/10 text-green' : color === 'yellow' ? 'bg-yellow/10 text-yellow' : color === 'red' ? 'bg-red/10 text-red' : 'bg-dim/10 text-dim')}>
                  <IconRobot className="w-4 h-4" />
                </div>
                <span className="font-medium text-sm truncate" title={a.name}>
                  {a.name}
                </span>
              </div>
              <span
                className={cn(
                  'text-[10px] font-bold uppercase tracking-wide',
                  color === 'green' && 'text-green',
                  color === 'yellow' && 'text-yellow',
                  color === 'red' && 'text-red',
                  color === 'dim' && 'text-dim'
                )}
              >
                {a.status}
              </span>
            </div>
            <div className="text-xs text-dim truncate" title={a.last_action}>
              {a.last_action || 'idle'}
            </div>
            <div className="flex items-center gap-1 text-[10px] text-dim/70 mt-2">
              <IconClock className="w-3 h-3" />
              {formatTime(a.last_updated)}
            </div>
            {a.error && <div className="text-xs text-red mt-2 truncate" title={a.error}>{a.error}</div>}
          </div>
        )
      })}
    </div>
  )
}
