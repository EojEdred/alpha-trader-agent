import { useState } from 'react'
import { IconPlayerPlay, IconRobot, IconChartBar } from '@tabler/icons-react'
import { api } from '../lib/api'

export default function Strategies() {
  const [task, setTask] = useState('Analyze AAPL for a swing trade')
  const [vcSymbol, setVcSymbol] = useState('AAPL')
  const [result, setResult] = useState(null)
  const [vcResult, setVcResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const [vcLoading, setVcLoading] = useState(false)
  const [error, setError] = useState('')

  const runAutoHedge = async () => {
    setLoading(true)
    setError('')
    setResult(null)
    try {
      const data = await api.runAutoHedge(task)
      setResult(data)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  const runValueCell = async () => {
    setVcLoading(true)
    setError('')
    setVcResult(null)
    try {
      const data = await api.runValueCell(vcSymbol)
      setVcResult(data)
    } catch (e) {
      setError(e.message)
    } finally {
      setVcLoading(false)
    }
  }

  return (
    <div className="space-y-5">
      <div className="bg-panel border border-border rounded-xl p-5">
        <h3 className="text-xs font-bold uppercase tracking-wide text-dim mb-4 flex items-center gap-2">
          <IconRobot className="w-4 h-4" /> AutoHedge
        </h3>
        <label className="block text-xs text-dim mb-1.5 uppercase tracking-wide">Task</label>
        <input
          value={task}
          onChange={(e) => setTask(e.target.value)}
          className="w-full bg-bg border border-border rounded-lg px-3 py-2 text-sm mb-3 focus:outline-none focus:border-blue"
        />
        <button
          onClick={runAutoHedge}
          disabled={loading}
          className="bg-blue hover:bg-blue/90 disabled:opacity-50 text-white text-sm font-semibold px-4 py-2 rounded-lg flex items-center gap-2"
        >
          {loading ? 'Running...' : <><IconPlayerPlay className="w-4 h-4" /> Run AutoHedge</>}
        </button>
        {result && (
          <div className="mt-4 space-y-3">
            <div className="text-sm">
              Status: <span className="font-bold">{result.status}</span> · Source: <span className="font-bold">{result.source || 'autohedge'}</span>
            </div>
            {result.result?.recommendations?.length > 0 && (
              <div className="grid gap-3 md:grid-cols-2">
                {result.result.recommendations.map((rec, i) => (
                  <div key={i} className="bg-bg border border-border rounded-lg p-3 text-sm">
                    <div className="font-bold text-lg">{rec.symbol}</div>
                    <div className={`uppercase font-bold ${rec.direction === 'long' ? 'text-green' : rec.direction === 'short' ? 'text-red' : 'text-dim'}`}>
                      {rec.direction}
                    </div>
                    <div className="mt-2 grid grid-cols-2 gap-2 text-xs text-dim">
                      <div>Entry: {rec.entry_price ?? 'N/A'}</div>
                      <div>Stop: {rec.stop_loss ?? 'N/A'}</div>
                      <div>Target: {rec.take_profit ?? 'N/A'}</div>
                      <div>Conf: {(rec.confidence * 100).toFixed(0)}%</div>
                    </div>
                  </div>
                ))}
              </div>
            )}
            {result.result?.thesis && (
              <div className="bg-bg border border-border rounded-lg p-3 text-sm">
                <div className="text-dim mb-1">Thesis</div>
                <div>{result.result.thesis}</div>
              </div>
            )}
          </div>
        )}
      </div>

      <div className="bg-panel border border-border rounded-xl p-5">
        <h3 className="text-xs font-bold uppercase tracking-wide text-dim mb-4 flex items-center gap-2">
          <IconChartBar className="w-4 h-4" /> ValueCell
        </h3>
        <label className="block text-xs text-dim mb-1.5 uppercase tracking-wide">Symbol</label>
        <input
          value={vcSymbol}
          onChange={(e) => setVcSymbol(e.target.value.toUpperCase())}
          className="w-full bg-bg border border-border rounded-lg px-3 py-2 text-sm mb-3 focus:outline-none focus:border-blue"
        />
        <button
          onClick={runValueCell}
          disabled={vcLoading}
          className="bg-blue hover:bg-blue/90 disabled:opacity-50 text-white text-sm font-semibold px-4 py-2 rounded-lg flex items-center gap-2"
        >
          {vcLoading ? 'Running...' : <><IconPlayerPlay className="w-4 h-4" /> Run ValueCell</>}
        </button>
        {vcResult && (
          <div className="mt-4 space-y-3 text-sm">
            <div className="flex items-center justify-between bg-bg p-3 rounded-lg border border-border">
              <span className="text-dim">Direction</span>
              <span className={`font-bold uppercase ${vcResult.direction === 'long' ? 'text-green' : vcResult.direction === 'short' ? 'text-red' : 'text-dim'}`}>
                {vcResult.direction}
              </span>
            </div>
            <div className="flex items-center justify-between bg-bg p-3 rounded-lg border border-border">
              <span className="text-dim">Confidence</span>
              <span className="font-bold">{(vcResult.confidence * 100).toFixed(0)}%</span>
            </div>
            <div className="bg-bg p-3 rounded-lg border border-border">
              <div className="text-dim mb-1">Reasoning</div>
              <div>{vcResult.reasoning}</div>
            </div>
          </div>
        )}
      </div>

      {error && <div className="text-red text-sm">{error}</div>}
    </div>
  )
}
