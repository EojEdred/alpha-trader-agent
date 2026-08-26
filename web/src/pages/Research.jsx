import { useEffect, useState } from 'react'
import { IconPlayerPlay, IconFileText, IconRefresh } from '@tabler/icons-react'
import { api } from '../lib/api'

export default function Research() {
  const [agendas, setAgendas] = useState([])
  const [selected, setSelected] = useState(null)
  const [content, setContent] = useState('')
  const [symbols, setSymbols] = useState('SPY,QQQ,AAPL')
  const [loading, setLoading] = useState(false)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState('')

  const loadAgendas = async () => {
    setLoading(true)
    setError('')
    try {
      const data = await api.researchAgendas()
      setAgendas(data.agendas || [])
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  const viewAgenda = async (name) => {
    setSelected(name)
    try {
      const data = await api.researchAgenda(name)
      setContent(data.content)
    } catch (e) {
      setContent(`Error loading agenda: ${e.message}`)
    }
  }

  const runResearch = async () => {
    setRunning(true)
    setError('')
    try {
      const list = symbols.split(',').map((s) => s.trim()).filter(Boolean)
      await api.runResearch(list.length ? list : null)
      setTimeout(loadAgendas, 2000)
    } catch (e) {
      setError(e.message)
    } finally {
      setRunning(false)
    }
  }

  useEffect(() => {
    loadAgendas()
  }, [])

  return (
    <div className="space-y-5">
      <div className="grid gap-4 lg:grid-cols-3">
        <div className="bg-panel border border-border rounded-xl p-5 lg:col-span-1">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-xs font-bold uppercase tracking-wide text-dim">Research Cycle</h3>
          </div>
          <label className="block text-xs text-dim mb-1.5 uppercase tracking-wide">Symbols (comma separated)</label>
          <input
            value={symbols}
            onChange={(e) => setSymbols(e.target.value)}
            className="w-full bg-bg border border-border rounded-lg px-3 py-2 text-sm mb-3 focus:outline-none focus:border-blue"
          />
          <button
            onClick={runResearch}
            disabled={running}
            className="w-full bg-blue hover:bg-blue/90 disabled:opacity-50 text-white text-sm font-semibold py-2 rounded-lg flex items-center justify-center gap-2"
          >
            {running ? <IconRefresh className="w-4 h-4 animate-spin" /> : <IconPlayerPlay className="w-4 h-4" />}
            {running ? 'Running...' : 'Run Auto-Research'}
          </button>
          {error && <div className="mt-3 text-red text-sm">{error}</div>}
        </div>

        <div className="bg-panel border border-border rounded-xl p-5 lg:col-span-2">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-xs font-bold uppercase tracking-wide text-dim">Latest Agenda Preview</h3>
            <button onClick={loadAgendas} className="text-xs text-dim hover:text-text flex items-center gap-1">
              <IconRefresh className="w-3 h-3" /> Refresh
            </button>
          </div>
          {selected ? (
            <div className="prose prose-invert max-w-none">
              <pre className="whitespace-pre-wrap text-sm text-text font-sans bg-bg p-4 rounded-lg border border-border">{content}</pre>
            </div>
          ) : (
            <div className="text-dim text-sm">Select an agenda from the list to view.</div>
          )}
        </div>
      </div>

      <div className="bg-panel border border-border rounded-xl p-5">
        <h3 className="text-xs font-bold uppercase tracking-wide text-dim mb-4">Saved Agendas</h3>
        {loading ? (
          <div className="text-dim text-sm">Loading...</div>
        ) : agendas.length === 0 ? (
          <div className="text-dim text-sm">No agendas yet. Run a research cycle.</div>
        ) : (
          <div className="space-y-2">
            {agendas.map((a) => (
              <button
                key={a.name}
                onClick={() => viewAgenda(a.name)}
                className={`w-full flex items-center justify-between px-4 py-3 rounded-lg text-sm border transition-colors ${
                  selected === a.name ? 'bg-blue/10 border-blue text-blue' : 'bg-bg border-border text-text hover:border-blue/50'
                }`}
              >
                <span className="flex items-center gap-2">
                  <IconFileText className="w-4 h-4" />
                  {a.name}
                </span>
                <span className="text-xs text-dim">{new Date(a.mtime * 1000).toLocaleString()}</span>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
