import { cn, statusColor } from '../lib/utils'

export default function StatusBadge({ status, className }) {
  const color = statusColor(status)
  const classes = {
    green: 'bg-green/10 text-green border-green/20',
    yellow: 'bg-yellow/10 text-yellow border-yellow/20',
    red: 'bg-red/10 text-red border-red/20',
    dim: 'bg-dim/10 text-dim border-dim/20',
  }

  return (
    <span
      className={cn(
        'inline-flex items-center px-2 py-0.5 rounded text-[11px] font-bold uppercase tracking-wide border',
        classes[color],
        className
      )}
    >
      {status}
    </span>
  )
}
