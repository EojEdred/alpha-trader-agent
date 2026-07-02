import PendingList from '../components/PendingList'
import { useAlphaTrader } from '../context/WebSocketContext'

export default function Pending() {
  const { pending } = useAlphaTrader()
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">Pending Confirmations</h2>
        <span className="text-sm text-dim">{pending.length} waiting</span>
      </div>
      <PendingList pending={pending} />
    </div>
  )
}
