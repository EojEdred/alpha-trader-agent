import { useState } from 'react'
import { IconSearch, IconTrendingUp } from '@tabler/icons-react'
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts'
import { api } from '../lib/api'

export default function MarketData() {
  const [symbol, setSymbol] = useState('AAPL')
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const fetchData = async () => {
    setLoading(true)
    setError('')
    setData(null)
    try {
      const res = await api.marketDataMassive(symbol)
      setData(res)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  const chartData = data?.ohlcv?.candles?.map((c) => ({
    time: c.timestamp ? new Date(c.timestamp).toLocaleDateString() : '',
    close: c.close,
    volume: c.volume,
  })) || []

  return (
    <div className="space-y-5">
      <div className="bg-panel border border-border rounded-xl p-5">
        <div className="flex items-center gap-3 mb-4">
          <input
            value={symbol}
            onChange={(e) => setSymbol(e.target.value.toUpperCase())}
            onKeyDown={(e) => e.key === 'Enter' && fetchData()}
            placeholder="Symbol"
            className="bg-bg border border-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-blue w-40"
          />
          <button
            onClick={fetchData}
            disabled={loading}
            className="bg-blue hover:bg-blue/90 disabled:opacity-50 text-white text-sm font-semibold px-4 py-2 rounded-lg flex items-center gap-2"
          >
            {loading ? 'Loading...' : <><IconSearch className="w-4 h-4" /> Fetch</>}
          </button>
        </div>
        {error && <div className="text-red text-sm">{error}</div>}
      </div>

      {data && (
        <>
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
            <div className="bg-panel border border-border rounded-xl p-4">
              <div className="text-xs text-dim uppercase tracking-wide mb-1">Source</div>
              <div className="font-bold text-sm">{data.source}</div>
            </div>
            <div className="bg-panel border border-border rounded-xl p-4">
              <div className="text-xs text-dim uppercase tracking-wide mb-1">Candles</div>
              <div className="font-bold text-sm">{data.ohlcv?.candles?.length || 0}</div>
            </div>
            <div className="bg-panel border border-border rounded-xl p-4">
              <div className="text-xs text-dim uppercase tracking-wide mb-1">Latest Close</div>
              <div className="font-bold text-sm">{data.ohlcv?.candles?.slice(-1)[0]?.close ?? 'N/A'}</div>
            </div>
            <div className="bg-panel border border-border rounded-xl p-4">
              <div className="text-xs text-dim uppercase tracking-wide mb-1">Snapshot</div>
              <div className="font-bold text-sm">{data.snapshot ? 'Available' : 'N/A'}</div>
            </div>
          </div>

          <div className="bg-panel border border-border rounded-xl p-5">
            <h3 className="text-xs font-bold uppercase tracking-wide text-dim mb-4 flex items-center gap-2">
              <IconTrendingUp className="w-4 h-4" /> Price History
            </h3>
            {chartData.length > 1 ? (
              <div className="h-72">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={chartData}>
                    <defs>
                      <linearGradient id="colorClose" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.3} />
                        <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
                    <XAxis dataKey="time" stroke="#6b7280" fontSize={10} tickLine={false} />
                    <YAxis stroke="#6b7280" fontSize={10} tickLine={false} domain={['auto', 'auto']} />
                    <Tooltip
                      contentStyle={{ backgroundColor: '#111827', borderColor: '#1f2937', color: '#e5e7eb' }}
                      itemStyle={{ color: '#3b82f6' }}
                    />
                    <Area type="monotone" dataKey="close" stroke="#3b82f6" fillOpacity={1} fill="url(#colorClose)" />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            ) : (
              <div className="text-dim text-sm">No price data available.</div>
            )}
          </div>

          {data.snapshot && (
            <div className="bg-panel border border-border rounded-xl p-5">
              <h3 className="text-xs font-bold uppercase tracking-wide text-dim mb-4">Raw Snapshot</h3>
              <pre className="bg-bg border border-border rounded-lg p-4 text-xs overflow-auto max-h-80">
                {JSON.stringify(data.snapshot, null, 2)}
              </pre>
            </div>
          )}
        </>
      )}
    </div>
  )
}
