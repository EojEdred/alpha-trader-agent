import StatusBadge from './StatusBadge'
import { formatTime, formatCurrency, cn } from '../lib/utils'

export default function TradeTable({ trades, compact = false }) {
  if (!trades || trades.length === 0) {
    return (
      <div className="bg-panel border border-border rounded-xl p-8 text-center text-dim text-sm">
        No trades recorded yet
      </div>
    )
  }

  return (
    <div className="bg-panel border border-border rounded-xl overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-left text-xs text-dim uppercase tracking-wide">
              <th className="px-4 py-3 font-medium">Time</th>
              <th className="px-4 py-3 font-medium">Symbol</th>
              <th className="px-4 py-3 font-medium">Direction</th>
              {!compact && <th className="px-4 py-3 font-medium">Size</th>}
              <th className="px-4 py-3 font-medium">Venue</th>
              {!compact && <th className="px-4 py-3 font-medium">Method</th>}
              <th className="px-4 py-3 font-medium">Status</th>
              <th className="px-4 py-3 font-medium">P&L</th>
              {!compact && <th className="px-4 py-3 font-medium">Error</th>}
            </tr>
          </thead>
          <tbody>
            {trades.map((t) => (
              <tr key={t.id} className="border-b border-border/50 hover:bg-panel-hover/50 transition-colors">
                <td className="px-4 py-3 text-dim whitespace-nowrap">{formatTime(t.timestamp)}</td>
                <td className="px-4 py-3 font-medium">{t.symbol}</td>
                <td className="px-4 py-3">
                  <span className={cn('font-medium', t.direction === 'long' ? 'text-green' : 'text-red')}>
                    {t.direction}
                  </span>
                </td>
                {!compact && <td className="px-4 py-3 text-dim">{t.size ?? '-'}</td>}
                <td className="px-4 py-3 text-dim">{t.venue}</td>
                {!compact && <td className="px-4 py-3 text-dim">{t.method}</td>}
                <td className="px-4 py-3">
                  <StatusBadge status={t.status} />
                </td>
                <td className={cn('px-4 py-3 font-medium', t.pnl > 0 ? 'text-green' : t.pnl < 0 ? 'text-red' : 'text-dim')}>
                  {formatCurrency(t.pnl)}
                </td>
                {!compact && (
                  <td className="px-4 py-3 text-red text-xs max-w-xs truncate">{t.error || ''}</td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
