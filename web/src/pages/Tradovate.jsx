import { useEffect, useState } from 'react'
import {
  IconBuildingBank,
  IconChartLine,
  IconCoin,
  IconLoader2,
  IconRefresh,
  IconWallet,
} from '@tabler/icons-react'
import { api } from '../lib/api'

export default function Tradovate() {
  const [account, setAccount] = useState(null)
  const [positions, setPositions] = useState([])
  const [orders, setOrders] = useState([])
  const [loading, setLoading] = useState({ account: false, positions: false, orders: false })
  const [error, setError] = useState('')

  const loadAccount = async () => {
    setLoading((prev) => ({ ...prev, account: true }))
    try {
      const data = await api.tradovateAccount()
      setAccount(data)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading((prev) => ({ ...prev, account: false }))
    }
  }

  const loadPositions = async () => {
    setLoading((prev) => ({ ...prev, positions: true }))
    try {
      const data = await api.tradovatePositions()
      setPositions(data.positions || [])
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading((prev) => ({ ...prev, positions: false }))
    }
  }

  const loadOrders = async () => {
    setLoading((prev) => ({ ...prev, orders: true }))
    try {
      const data = await api.tradovateOrders()
      setOrders(data.orders || [])
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading((prev) => ({ ...prev, orders: false }))
    }
  }

  const loadAll = () => {
    setError('')
    loadAccount()
    loadPositions()
    loadOrders()
  }

  useEffect(() => {
    loadAll()
    const interval = setInterval(loadAll, 10000)
    return () => clearInterval(interval)
  }, [])

  const balance = account?.cash_balance || {}
  const cash = balance.cashValue || balance.cash || 0
  const buyingPower = balance.buyingPower || 0
  const realizedPnl = balance.realizedPnl || 0
  const unrealizedPnl = balance.unrealizedPnl || 0

  return (
    <div className="space-y-5">
      <div className="bg-panel border border-border rounded-xl p-5">
        <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
          <div>
            <h3 className="text-xs font-bold uppercase tracking-wide text-dim flex items-center gap-2">
              <IconBuildingBank className="w-4 h-4" /> Apex / Tradovate
            </h3>
            <p className="text-sm text-dim mt-1">
              Funded futures account overview, positions, and working orders via Tradovate API.
            </p>
          </div>
          <button
            onClick={loadAll}
            disabled={Object.values(loading).some(Boolean)}
            className="flex items-center gap-2 px-3 py-1.5 text-sm font-medium border border-border rounded-lg hover:bg-panel-hover transition-colors"
          >
            <IconRefresh className={`w-4 h-4 ${Object.values(loading).some(Boolean) ? 'animate-spin' : ''}`} />
            Refresh
          </button>
        </div>
      </div>

      {error && <div className="bg-red/10 text-red border border-red/20 rounded-xl p-4 text-sm">{error}</div>}

      {!account && !loading.account && !error && (
        <div className="bg-panel border border-border rounded-xl p-8 text-center text-dim text-sm">
          Tradovate credentials not configured. Add them in Settings → Apex / Tradovate.
        </div>
      )}

      {account && (
        <>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
            <div className="bg-panel border border-border rounded-xl p-4">
              <div className="flex items-center gap-2 text-dim text-xs font-bold uppercase tracking-wide mb-2">
                <IconWallet className="w-4 h-4" /> Cash
              </div>
              <div className="text-2xl font-semibold tracking-tight">${cash.toLocaleString(undefined, { minimumFractionDigits: 2 })}</div>
            </div>
            <div className="bg-panel border border-border rounded-xl p-4">
              <div className="flex items-center gap-2 text-dim text-xs font-bold uppercase tracking-wide mb-2">
                <IconCoin className="w-4 h-4" /> Buying Power
              </div>
              <div className="text-2xl font-semibold tracking-tight">${buyingPower.toLocaleString(undefined, { minimumFractionDigits: 2 })}</div>
            </div>
            <div className="bg-panel border border-border rounded-xl p-4">
              <div className="flex items-center gap-2 text-dim text-xs font-bold uppercase tracking-wide mb-2">
                <IconChartLine className="w-4 h-4" /> Realized P&L
              </div>
              <div className={`text-2xl font-semibold tracking-tight ${realizedPnl >= 0 ? 'text-green' : 'text-red'}`}>
                ${realizedPnl.toLocaleString(undefined, { minimumFractionDigits: 2 })}
              </div>
            </div>
            <div className="bg-panel border border-border rounded-xl p-4">
              <div className="flex items-center gap-2 text-dim text-xs font-bold uppercase tracking-wide mb-2">
                <IconChartLine className="w-4 h-4" /> Unrealized P&L
              </div>
              <div className={`text-2xl font-semibold tracking-tight ${unrealizedPnl >= 0 ? 'text-green' : 'text-red'}`}>
                ${unrealizedPnl.toLocaleString(undefined, { minimumFractionDigits: 2 })}
              </div>
            </div>
          </div>

          <div className="bg-panel border border-border rounded-xl p-5">
            <h4 className="text-xs font-bold uppercase tracking-wide text-dim mb-4">Positions</h4>
            {positions.length === 0 ? (
              <div className="text-sm text-dim">No open positions.</div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-dim border-b border-border">
                      <th className="pb-2 font-medium">Symbol</th>
                      <th className="pb-2 font-medium">Side</th>
                      <th className="pb-2 font-medium">Size</th>
                      <th className="pb-2 font-medium">Entry</th>
                      <th className="pb-2 font-medium">Current</th>
                      <th className="pb-2 font-medium">P&L</th>
                    </tr>
                  </thead>
                  <tbody>
                    {positions.map((pos, idx) => (
                      <tr key={idx} className="border-b border-border/50 last:border-0">
                        <td className="py-3 font-medium">{pos.symbol}</td>
                        <td className={`py-3 capitalize ${pos.side === 'long' ? 'text-green' : 'text-red'}`}>{pos.side}</td>
                        <td className="py-3">{pos.size}</td>
                        <td className="py-3">{pos.entry_price}</td>
                        <td className="py-3">{pos.current_price}</td>
                        <td className={`py-3 ${(pos.pnl || 0) >= 0 ? 'text-green' : 'text-red'}`}>{pos.pnl}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          <div className="bg-panel border border-border rounded-xl p-5">
            <h4 className="text-xs font-bold uppercase tracking-wide text-dim mb-4">Working Orders</h4>
            {orders.length === 0 ? (
              <div className="text-sm text-dim">No working orders.</div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-dim border-b border-border">
                      <th className="pb-2 font-medium">Symbol</th>
                      <th className="pb-2 font-medium">Action</th>
                      <th className="pb-2 font-medium">Qty</th>
                      <th className="pb-2 font-medium">Type</th>
                      <th className="pb-2 font-medium">Price</th>
                      <th className="pb-2 font-medium">Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {orders.map((order, idx) => (
                      <tr key={idx} className="border-b border-border/50 last:border-0">
                        <td className="py-3 font-medium">{order.symbol}</td>
                        <td className="py-3">{order.action}</td>
                        <td className="py-3">{order.orderQty}</td>
                        <td className="py-3">{order.orderType}</td>
                        <td className="py-3">{order.price || '-'}</td>
                        <td className="py-3">{order.ordStatus}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  )
}
