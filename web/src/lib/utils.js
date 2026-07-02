import { format, formatDistanceToNow } from 'date-fns'

export function cn(...classes) {
  return classes.filter(Boolean).join(' ')
}

export function formatDuration(seconds) {
  if (!seconds || seconds < 0) return '0s'
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = Math.floor(seconds % 60)
  const parts = []
  if (h) parts.push(`${h}h`)
  if (m) parts.push(`${m}m`)
  if (s || parts.length === 0) parts.push(`${s}s`)
  return parts.join(' ')
}

export function formatTime(iso) {
  if (!iso) return '-'
  try {
    return format(new Date(iso), 'MMM d, HH:mm:ss')
  } catch {
    return iso
  }
}

export function timeAgo(iso) {
  if (!iso) return '-'
  try {
    return formatDistanceToNow(new Date(iso), { addSuffix: true })
  } catch {
    return iso
  }
}

export function formatCurrency(value) {
  if (value == null) return '-'
  const num = Number(value)
  const abs = Math.abs(num)
  const sign = num < 0 ? '-' : ''
  if (abs >= 1000) return `${sign}$${(abs / 1000).toFixed(2)}k`
  return `${sign}$${abs.toFixed(2)}`
}

export function statusColor(status) {
  const s = String(status || '').toLowerCase()
  if (['running', 'filled', 'approved', 'idle', 'success', 'ok'].includes(s)) return 'green'
  if (['paused', 'pending', 'starting', 'busy'].includes(s)) return 'yellow'
  if (['stopped', 'offline', 'rejected', 'failed', 'error'].includes(s)) return 'red'
  return 'dim'
}
