import { useEffect, useState } from 'react'
import { IconPlayerPlay, IconRefresh, IconRobot } from '@tabler/icons-react'
import { api } from '../lib/api'

export default function Analysts() {
  const [analysts, setAnalysts] = useState([])
  const [symbol, setSymbol] = useState('AAPL')
  const [selected, setSelected] = useState('')
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const loadAnalysts = async () => {
    try {
      const data = await api.analysts()
      setAnalysts(data.analysts || [])
      if (data.analysts?.length && !selected) {
        setSelected(data.analysts[0].name)
      }
    } catch (e) {
      setError(e.message)
    }
  }

  const runAnalyst = async () => {
    if (!selected || !symbol) return
    setLoading(true)
    setError('')
    setResult(null)
    try {
      const data = await api.runAnalyst(selected, symbol)
      setResult(data)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadAnalysts()
  }, [])

  return (
    <div className="space-y-5">
      <div className="grid gap-4 lg:grid-cols-3">
        <div className="bg-panel border border-border rounded-xl p-5 lg:col-span-1">
          <h3 className="text-xs font-bold uppercase tracking-wide text-dim mb-4">Run Analyst</h3>
          <label className="block text-xs text-dim mb-1.5 uppercase tracking-wide">Symbol</label>
          <input
            value={symbol}
            onChange={(e) => setSymbol(e.target.value.toUpperCase())}
            className="w-full bg-bg border border-border rounded-lg px-3 py-2 text-sm mb-3 focus:outline-none focus:border-blue"
          />
          <label className="block text-xs text-dim mb-1.5 uppercase tracking-wide">Analyst</label>
          <select
            value={selected}
            onChange={(e) => setSelected(e.target.value)}
            className="w-full bg-bg border border-border rounded-lg px-3 py-2 text-sm mb-3 focus:outline-none focus:border-blue"
          >
            {analysts.map((a) => (
              <option key={a.name} value={a.name}>
                {a.name} (w: {a.weight})
              </option>
            ))}
          </select>
          <button
            onClick={runAnalyst}
            disabled={loading}
            className="w-full bg-blue hover:bg-blue/90 disabled:opacity-50 text-white text-sm font-semibold py-2 rounded-lg flex items-center justify-center gap-2"
          >
            {loading ? <IconRefresh className="w-4 h-4 animate-spin" /> : <IconPlayerPlay className="w-4 h-4" />}
            {loading ? 'Running...' : 'Run Analysis'}
          </button>
          {error && <div className="mt-3 text-red text-sm">{error}</div>}
        </div>

        <div className="bg-panel border border-border rounded-xl p-5 lg:col-span-2">
          <h3 className="text-xs font-bold uppercase tracking-wide text-dim mb-4">Result</h3>
          {result ? (
            <div className="space-y-3 text-sm">
              <div className="flex items-center justify-between bg-bg p-3 rounded-lg border border-border">
                <span className="text-dim">Direction</span>
                <span className={`font-bold uppercase ${result.direction === 'long' ? 'text-green' : result.direction === 'short' ? 'text-red' : 'text-dim'}`}>
                  {result.direction}
                </span>
              </div>
              <div className="flex items-center justify-between bg-bg p-3 rounded-lg border border-border">
                <span className="text-dim">Confidence</span>
                <span className="font-bold">{(result.confidence * 100).toFixed(0)}%</span>
              </div>
              <div className="bg-bg p-3 rounded-lg border border-border">
                <div className="text-dim mb-1">Reasoning</div>
                <div>{result.reasoning}</div>
              </div>
              {result.key_points?.length > 0 && (
                <div className="bg-bg p-3 rounded-lg border border-border">
                  <div className="text-dim mb-1">Key Points</div>
                  <ul className="list-disc list-inside space-y-1">
                    {result.key_points.map((p, i) => (
                      <li key={i}>{p}</li>
                    ))}
                  </ul>
                </div>
              )}
              {result.risks?.length > 0 && (
                <div className="bg-bg p-3 rounded-lg border border-border">
                  <div className="text-dim mb-1">Risks</div>
                  <ul className="list-disc list-inside space-y-1">
                    {result.risks.map((r, i) => (
                      <li key={i}>{r}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          ) : (
            <div className="text-dim text-sm flex items-center gap-2">
              <IconRobot className="w-4 h-4" />
              Run an analyst to see the report.
            </div>
          )}
        </div>
      </div>

      <div className="bg-panel border border-border rounded-xl p-5">
        <h3 className="text-xs font-bold uppercase tracking-wide text-dim mb-4">Analyst Weights</h3>
        <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
          {analysts.map((a) => (
            <div key={a.name} className="bg-bg border border-border rounded-lg p-3">
              <div className="font-medium text-sm">{a.name}</div>
              <div className="text-xs text-dim">{a.description || 'No description'}</div>
              <div className="mt-2 text-xs font-mono text-blue">weight {a.weight}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
