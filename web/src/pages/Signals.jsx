import { useEffect, useState } from 'react'
import {
  IconBell,
  IconCopy,
  IconExternalLink,
  IconRefresh,
  IconSearch,
  IconCheck,
} from '@tabler/icons-react'
import { api } from '../lib/api'

const SOURCE_LABELS = {
  auto_research: 'Auto Research',
  autohedge: 'AutoHedge',
  valuecell: 'ValueCell',
  phantomflow: 'TradingView',
  manual: 'Manual',
}

const SOURCE_COLORS = {
  auto_research: 'bg-blue/10 text-blue',
  autohedge: 'bg-purple/10 text-purple',
  valuecell: 'bg-green/10 text-green',
  phantomflow: 'bg-orange/10 text-orange',
  manual: 'bg-dim/10 text-dim',
}

export default function Signals() {
  const [signals, setSignals] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [sourceFilter, setSourceFilter] = useState('')
  const [symbolFilter, setSymbolFilter] = useState('')
  const [copying, setCopying] = useState({})
  const [copyResult, setCopyResult] = useState({})
  const [copyVenue, setCopyVenue] = useState('tradovate')

  const loadSignals = async () => {
    setLoading(true)
    setError('')
    try {
      const params = {}
      if (sourceFilter) params.source = sourceFilter
      if (symbolFilter) params.symbol = symbolFilter.toUpperCase()
      const data = await api.signals(params)
      setSignals(data || [])
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  const copySignal = async (signal) => {
    setCopying((prev) => ({ ...prev, [signal.id]: true }))
    setCopyResult((prev) => ({ ...prev, [signal.id]: '' }))
    try {
      const result = await api.copySignal(signal.id, {
        venue: copyVenue,
        size: signal.size || 1,
      })
      setCopyResult((prev) => ({
        ...prev,
        [signal.id]: `Copied → ${result.intent_id}`,
      }))
      setTimeout(loadSignals, 500)
    } catch (e) {
      setCopyResult((prev) => ({ ...prev, [signal.id]: `Error: ${e.message}` }))
    } finally {
      setCopying((prev) => ({ ...prev, [signal.id]: false }))
    }
  }

  useEffect(() => {
    loadSignals()
    const interval = setInterval(loadSignals, 5000)
    return () => clearInterval(interval)
  }, [sourceFilter, symbolFilter])

  return (
    <div className="space-y-5">
      <div className="bg-panel border border-border rounded-xl p-5">
        <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
          <div>
            <h3 className="text-xs font-bold uppercase tracking-wide text-dim flex items-center gap-2">
              <IconBell className="w-4 h-4" /> Signal Feed
            </h3>
            <p className="text-sm text-dim mt-1">
              Copy actionable ideas from TradingView, Unusual Whales, Massive, AutoHedge, ValueCell, and auto-research.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <div className="relative">
              <IconSearch className="w-4 h-4 absolute left-2.5 top-1/2 -translate-y-1/2 text-dim" />
              <input
                value={symbolFilter}
                onChange={(e) => setSymbolFilter(e.target.value)}
                placeholder="Symbol..."
                className="pl-8 pr-3 py-1.5 bg-bg border border-border rounded-lg text-sm focus:outline-none focus:border-blue"
              />
            </div>
            <select
              value={sourceFilter}
              onChange={(e) => setSourceFilter(e.target.value)}
              className="bg-bg border border-border rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:border-blue"
            >
              <option value="">All sources</option>
              {Object.entries(SOURCE_LABELS).map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
            </select>
            <select
              value={copyVenue}
              onChange={(e) => setCopyVenue(e.target.value)}
              className="bg-bg border border-border rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:border-blue"
            >
              <option value="tradovate">Copy to Apex/Tradovate</option>
              <option value="apex">Copy to Apex (legacy)</option>
              <option value="oanda">Copy to OANDA</option>
              <option value="schwab">Copy to Schwab</option>
              <option value="topstep">Copy to Topstep</option>
            </select>
            <button
              onClick={loadSignals}
              disabled={loading}
              className="p-1.5 text-dim hover:text-text border border-border rounded-lg"
            >
              <IconRefresh className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            </button>
          </div>
        </div>
      </div>

      {error && <div className="bg-red/10 text-red border border-red/20 rounded-xl p-4 text-sm">{error}</div>}

      <div className="space-y-3">
        {signals.length === 0 && !loading ? (
          <div className="bg-panel border border-border rounded-xl p-8 text-center text-dim text-sm">
            No signals yet. Run research, AutoHedge, ValueCell, or receive a TradingView webhook.
          </div>
        ) : (
          signals.map((signal) => {
            const dirColor = signal.direction === 'long' ? 'text-green' : signal.direction === 'short' ? 'text-red' : 'text-dim'
            const copied = signal.copied || copyResult[signal.id]?.startsWith('Copied')
            return (
              <div
                key={signal.id}
                className={`bg-panel border rounded-xl p-4 transition-colors ${copied ? 'border-green/30' : 'border-border hover:border-blue/30'}`}
              >
                <div className="flex flex-col lg:flex-row lg:items-start lg:justify-between gap-4">
                  <div className="flex-1 space-y-2">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className={`text-[10px] font-bold uppercase tracking-wide px-2 py-0.5 rounded ${SOURCE_COLORS[signal.source] || 'bg-dim/10 text-dim'}`}>
                        {SOURCE_LABELS[signal.source] || signal.source}
                      </span>
                      <span className="font-bold text-text">{signal.symbol}</span>
                      <span className={`text-xs font-bold uppercase ${dirColor}`}>{signal.direction}</span>
                      <span className="text-xs text-dim">{(signal.confidence * 100).toFixed(0)}% confidence</span>
                      {copied && <span className="text-[10px] text-green flex items-center gap-1"><IconCheck className="w-3 h-3" /> Copied</span>}
                    </div>

                    <p className="text-sm text-text/90 line-clamp-2">{signal.rationale || 'No rationale provided.'}</p>

                    <div className="flex flex-wrap gap-3 text-xs text-dim">
                      {signal.size && <span>Size: <span className="text-text">{signal.size}</span></span>}
                      {signal.entry_price ? <span>Entry: <span className="text-text">{signal.entry_price}</span></span> : null}
                      {signal.stop_price ? <span>Stop: <span className="text-text">{signal.stop_price}</span></span> : null}
                      {signal.target_price ? <span>Target: <span className="text-text">{signal.target_price}</span></span> : null}
                      <span>{new Date(signal.timestamp).toLocaleString()}</span>
                    </div>
                  </div>

                  <div className="flex items-center gap-2">
                    {signal.source_url && (
                      <a
                        href={signal.source_url}
                        target="_blank"
                        rel="noreferrer"
                        className="flex items-center gap-1 px-3 py-1.5 text-xs font-medium border border-border rounded-lg hover:bg-panel-hover transition-colors"
                      >
                        <IconExternalLink className="w-3.5 h-3.5" /> Source
                      </a>
                    )}
                    <button
                      onClick={() => copySignal(signal)}
                      disabled={copying[signal.id] || copied}
                      className="flex items-center gap-1 px-3 py-1.5 text-xs font-medium bg-blue hover:bg-blue/90 disabled:opacity-50 text-white rounded-lg transition-colors"
                    >
                      {copying[signal.id] ? (
                        <IconRefresh className="w-3.5 h-3.5 animate-spin" />
                      ) : (
                        <IconCopy className="w-3.5 h-3.5" />
                      )}
                      {copied ? 'Copied' : `Copy to ${copyVenue === 'tradovate' ? 'Apex/Tradovate' : copyVenue.charAt(0).toUpperCase() + copyVenue.slice(1)}`}
                    </button>
                  </div>
                </div>

                {copyResult[signal.id] && !copyResult[signal.id].startsWith('Copied') && (
                  <div className="mt-3 text-xs text-red">{copyResult[signal.id]}</div>
                )}
                {copyResult[signal.id]?.startsWith('Copied') && (
                  <div className="mt-3 text-xs text-green">{copyResult[signal.id]}</div>
                )}
              </div>
            )
          })
        )}
      </div>
    </div>
  )
}
