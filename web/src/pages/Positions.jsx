import { IconBuildingBank } from '@tabler/icons-react'
import { useAlphaTrader } from '../context/WebSocketContext'
import TradeTable from '../components/TradeTable'

export default function Positions() {
  const { positions, trades } = useAlphaTrader()
  const brokerPositions = positions.positions || []
  const openTrades = trades.filter((t) => t.status && !['closed', 'cancelled', 'rejected'].includes(t.status.toLowerCase()))

  return (
    <div className="space-y-5">
      <div className="grid gap-5 lg:grid-cols-2">
        <div className="bg-panel border border-border rounded-xl p-5">
          <div className="flex items-center gap-2 mb-4">
            <IconBuildingBank className="w-4 h-4 text-blue" />
            <h3 className="text-xs font-bold uppercase tracking-wide text-dim">Broker Positions</h3>
          </div>
          {brokerPositions.length === 0 ? (
            <div className="text-center text-dim text-sm py-8">No broker positions fetched</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border text-left text-xs text-dim uppercase tracking-wide">
                    <th className="px-3 py-2">Symbol</th>
                    <th className="px-3 py-2">Size</th>
                    <th className="px-3 py-2">Side</th>
                    <th className="px-3 py-2">Entry</th>
                    <th className="px-3 py-2">Market</th>
                    <th className="px-3 py-2">P&L</th>
                  </tr>
                </thead>
                <tbody>
                  {brokerPositions.map((p, i) => (
                    <tr key={i} className="border-b border-border/50">
                      <td className="px-3 py-2">{p.symbol || p.instrument || '-'}</td>
                      <td className="px-3 py-2">{p.size ?? p.quantity ?? p.units ?? '-'}</td>
                      <td className="px-3 py-2">{p.side || p.direction || '-'}</td>
                      <td className="px-3 py-2">{p.entry != null ? p.entry : p.average_price ?? '-'}</td>
                      <td className="px-3 py-2">{p.market_price != null ? p.market_price : '-'}</td>
                      <td className="px-3 py-2">{p.pnl != null ? `$${Number(p.pnl).toFixed(2)}` : '-'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <div className="bg-panel border border-border rounded-xl p-5">
          <h3 className="text-xs font-bold uppercase tracking-wide text-dim mb-4">Open State Trades</h3>
          {openTrades.length === 0 ? (
            <div className="text-center text-dim text-sm py-8">No open trades</div>
          ) : (
            <TradeTable trades={openTrades} compact />
          )}
        </div>
      </div>
    </div>
  )
}
