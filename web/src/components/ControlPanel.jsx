import { useState } from 'react'
import { IconPlayerPlay, IconPlayerPause, IconSquare, IconLoader2, IconSend, IconRun, IconRefresh } from '@tabler/icons-react'
import { useAlphaTrader } from '../context/WebSocketContext'

export default function ControlPanel() {
  const { status, workflows, sendCommand } = useAlphaTrader()
  const [loading, setLoading] = useState({})
  const [trade, setTrade] = useState({ symbol: '', direction: 'long', size: 1, venue: 'oanda' })
  const [selectedWorkflow, setSelectedWorkflow] = useState('')
  const [toast, setToast] = useState('')

  const showToast = (msg) => {
    setToast(msg)
    setTimeout(() => setToast(''), 3000)
  }

  const runAction = async (name, ...args) => {
    setLoading((l) => ({ ...l, [name]: true }))
    try {
      await sendCommand(name, ...args)
      showToast(`${name} ok`)
    } catch (e) {
      showToast(e.message)
    } finally {
      setLoading((l) => ({ ...l, [name]: false }))
    }
  }

  const handleTradeSubmit = async (e) => {
    e.preventDefault()
    await runAction('trade', trade)
    setTrade({ symbol: '', direction: 'long', size: 1, venue: 'oanda' })
  }

  const handleRunWorkflow = async () => {
    if (!selectedWorkflow) return
    await runAction('runWorkflow', selectedWorkflow)
  }

  return (
    <div className="space-y-5">
      {toast && (
        <div className="fixed bottom-5 right-5 bg-panel border-l-4 border-blue text-text px-4 py-3 rounded shadow-2xl text-sm z-50">
          {toast}
        </div>
      )}

      <div className="grid gap-5 lg:grid-cols-2">
        <div className="bg-panel border border-border rounded-xl p-5">
          <h3 className="text-xs font-bold uppercase tracking-wide text-dim mb-4">Engine Control</h3>
          <div className="flex gap-3">
            <button
              onClick={() => runAction('control', 'start')}
              disabled={loading.control || status.mode === 'running'}
              className="flex items-center gap-2 px-4 py-2 bg-green/10 hover:bg-green/20 text-green rounded-lg font-semibold transition-colors disabled:opacity-50"
            >
              {loading.control ? <IconLoader2 className="w-4 h-4 animate-spin" /> : <IconPlayerPlay className="w-4 h-4" />}
              Start
            </button>
            <button
              onClick={() => runAction('control', 'pause')}
              disabled={loading.control || status.mode !== 'running'}
              className="flex items-center gap-2 px-4 py-2 bg-yellow/10 hover:bg-yellow/20 text-yellow rounded-lg font-semibold transition-colors disabled:opacity-50"
            >
              {loading.control ? <IconLoader2 className="w-4 h-4 animate-spin" /> : <IconPlayerPause className="w-4 h-4" />}
              Pause
            </button>
            <button
              onClick={() => runAction('control', 'stop')}
              disabled={loading.control}
              className="flex items-center gap-2 px-4 py-2 bg-red/10 hover:bg-red/20 text-red rounded-lg font-semibold transition-colors disabled:opacity-50"
            >
              {loading.control ? <IconLoader2 className="w-4 h-4 animate-spin" /> : <IconSquare className="w-4 h-4" />}
              Stop
            </button>
            <button
              onClick={() => runAction('serviceRestart')}
              disabled={loading.serviceRestart}
              className="flex items-center gap-2 px-4 py-2 bg-blue/10 hover:bg-blue/20 text-blue rounded-lg font-semibold transition-colors disabled:opacity-50"
            >
              {loading.serviceRestart ? <IconLoader2 className="w-4 h-4 animate-spin" /> : <IconRefresh className="w-4 h-4" />}
              Restart Service
            </button>
          </div>
        </div>

        <div className="bg-panel border border-border rounded-xl p-5">
          <h3 className="text-xs font-bold uppercase tracking-wide text-dim mb-4">Manual Trade</h3>
          <form onSubmit={handleTradeSubmit} className="space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <input
                type="text"
                placeholder="Symbol"
                value={trade.symbol}
                onChange={(e) => setTrade({ ...trade, symbol: e.target.value })}
                required
                className="bg-bg border border-border rounded-lg px-3 py-2 text-sm text-text placeholder:text-dim/50 focus:outline-none focus:border-blue"
              />
              <select
                value={trade.direction}
                onChange={(e) => setTrade({ ...trade, direction: e.target.value })}
                className="bg-bg border border-border rounded-lg px-3 py-2 text-sm text-text focus:outline-none focus:border-blue"
              >
                <option value="long">Long</option>
                <option value="short">Short</option>
              </select>
              <input
                type="number"
                placeholder="Size"
                value={trade.size}
                onChange={(e) => setTrade({ ...trade, size: Number(e.target.value) })}
                required
                className="bg-bg border border-border rounded-lg px-3 py-2 text-sm text-text placeholder:text-dim/50 focus:outline-none focus:border-blue"
              />
              <select
                value={trade.venue}
                onChange={(e) => setTrade({ ...trade, venue: e.target.value })}
                className="bg-bg border border-border rounded-lg px-3 py-2 text-sm text-text focus:outline-none focus:border-blue"
              >
                <option value="oanda">OANDA</option>
                <option value="schwab">Schwab</option>
                <option value="topstep">Topstep</option>
                <option value="kalshi">Kalshi</option>
                <option value="polymarket">Polymarket</option>
              </select>
            </div>
            <button
              type="submit"
              disabled={loading.trade}
              className="w-full flex items-center justify-center gap-2 bg-blue hover:bg-blue/90 disabled:opacity-50 text-white font-semibold py-2 rounded-lg transition-colors"
            >
              {loading.trade ? <IconLoader2 className="w-4 h-4 animate-spin" /> : <IconSend className="w-4 h-4" />}
              Submit Trade
            </button>
          </form>
        </div>
      </div>

      <div className="bg-panel border border-border rounded-xl p-5">
        <h3 className="text-xs font-bold uppercase tracking-wide text-dim mb-4">Run Workflow</h3>
        <div className="flex gap-3">
          <select
            value={selectedWorkflow}
            onChange={(e) => setSelectedWorkflow(e.target.value)}
            className="flex-1 bg-bg border border-border rounded-lg px-3 py-2 text-sm text-text focus:outline-none focus:border-blue"
          >
            <option value="">Select a workflow</option>
            {workflows.map((w) => (
              <option key={w.id} value={w.id}>{w.name}</option>
            ))}
          </select>
          <button
            onClick={handleRunWorkflow}
            disabled={!selectedWorkflow || loading.runWorkflow}
            className="flex items-center gap-2 px-4 py-2 bg-blue hover:bg-blue/90 disabled:opacity-50 text-white rounded-lg font-semibold transition-colors"
          >
            {loading.runWorkflow ? <IconLoader2 className="w-4 h-4 animate-spin" /> : <IconRun className="w-4 h-4" />}
            Run
          </button>
        </div>
      </div>
    </div>
  )
}
