import TradeTable from '../components/TradeTable'
import { useAlphaTrader } from '../context/WebSocketContext'

export default function Trades() {
  const { trades } = useAlphaTrader()
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">Trade History</h2>
        <span className="text-sm text-dim">{trades.length} trades</span>
      </div>
      <TradeTable trades={trades} />
    </div>
  )
}
