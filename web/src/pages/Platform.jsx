import { useEffect, useMemo, useState } from 'react'
import {
  IconAffiliate,
  IconBrain,
  IconChartCandle,
  IconDeviceDesktop,
  IconPlayerPlay,
} from '@tabler/icons-react'
import { api } from '../lib/api'

function Dot({ ok }) {
  return (
    <span className={`inline-block w-2 h-2 rounded-full ${ok ? 'bg-green' : 'bg-red'}`} />
  )
}

function Panel({ title, icon: Icon, children, className = '' }) {
  return (
    <section className={`border border-[#1f2a36] bg-[#0f1419] rounded-lg overflow-hidden ${className}`}>
      <header className="flex items-center gap-2 px-3 py-2 border-b border-[#1f2a36] text-[11px] uppercase tracking-wider text-[#8b9bb4]">
        {Icon ? <Icon className="w-3.5 h-3.5" /> : null}
        {title}
      </header>
      <div className="p-3">{children}</div>
    </section>
  )
}

function CandleChart({ candles, symbol }) {
  const bars = (candles || []).slice(-90)
  const { path, w, h } = useMemo(() => {
    const width = 640
    const height = 220
    if (bars.length < 2) return { path: '', w: width, h: height }
    const highs = bars.map((c) => Number(c.high) || 0)
    const lows = bars.map((c) => Number(c.low) || 0)
    const max = Math.max(...highs)
    const min = Math.min(...lows.filter((n) => n > 0))
    const span = max - min || 1
    const bw = width / bars.length
    const d = bars
      .map((c, i) => {
        const x = i * bw + bw / 2
        const y = height - ((Number(c.close) - min) / span) * (height - 8) - 4
        return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`
      })
      .join(' ')
    return { path: d, w: width, h: height }
  }, [bars])
  if (!path) {
    return <div className="h-[220px] flex items-center justify-center text-[#8b9bb4] text-xs">No candles for {symbol}</div>
  }
  const last = bars[bars.length - 1]
  const up = Number(last?.close) >= Number(last?.open)
  return (
    <div>
      <svg viewBox={`0 0 ${w} ${h}`} className="w-full h-[220px]">
        <path d={path} fill="none" stroke={up ? '#26a69a' : '#ef5350'} strokeWidth="1.6" />
      </svg>
      <div className="text-[11px] text-[#8b9bb4]">
        {symbol} · {bars.length} bars · last {Number(last?.close || 0).toFixed(2)}
      </div>
    </div>
  )
}

export default function Platform() {
  const [status, setStatus] = useState(null)
  const [brain, setBrain] = useState(null)
  const [inventory, setInventory] = useState(null)
  const [desk, setDesk] = useState(null)
  const [quotes, setQuotes] = useState([])
  const [candles, setCandles] = useState([])
  const [news, setNews] = useState([])
  const [symbol, setSymbol] = useState('SPY')
  const [venue, setVenue] = useState('paper')
  const [size, setSize] = useState(1)
  const [ticket, setTicket] = useState('Dry-run until armed.')
  const [chatLog, setChatLog] = useState([])
  const [chatInput, setChatInput] = useState('')
  const [error, setError] = useState('')
  const [task, setTask] = useState('Analyze AAPL vs QQQ hedge')
  const [hedge, setHedge] = useState(null)
  const [busy, setBusy] = useState(false)
  const [finceptMsg, setFinceptMsg] = useState('')

  const load = async () => {
    try {
      const [s, inv, br, d, q] = await Promise.all([
        api.platformStatus(),
        api.platformInventory(),
        api.platformBrain().catch(() => null),
        api.platformDesk().catch(() => null),
        api.platformQuotes().catch(() => ({ quotes: [] })),
      ])
      setStatus(s)
      setInventory(inv)
      setBrain(br)
      setDesk(d)
      setQuotes(q.quotes || [])
      setError('')
    } catch (e) {
      setError(e.message)
    }
  }

  const loadChart = async (sym = symbol) => {
    try {
      const data = await api.platformOhlcv(sym, '1d')
      setCandles(data.candles || [])
      if (data.symbol) setSymbol(data.symbol)
    } catch (e) {
      setCandles([])
    }
  }

  const loadNews = async (sym = symbol) => {
    try {
      const data = await api.platformNews(sym)
      setNews(data.articles || [])
    } catch {
      setNews([])
    }
  }

  useEffect(() => {
    load()
    loadChart('SPY')
    loadNews('SPY')
    const id = setInterval(load, 15000)
    return () => clearInterval(id)
  }, [])

  const pickSymbol = (sym) => {
    const s = String(sym || '').toUpperCase()
    if (!s) return
    setSymbol(s)
    loadChart(s)
    loadNews(s)
  }

  const launchFincept = async () => {
    try {
      const res = await api.launchFincept()
      setFinceptMsg(res.status)
    } catch (e) {
      setFinceptMsg(e.message)
    }
  }

  const runHedge = async () => {
    setBusy(true)
    try {
      const data = await api.runAutoHedge(task)
      setHedge(data)
    } catch (e) {
      setHedge({ status: 'error', detail: e.message })
    } finally {
      setBusy(false)
    }
  }

  const sendChat = async () => {
    const msg = chatInput.trim()
    if (!msg) return
    setChatInput('')
    setChatLog((rows) => [...rows, { who: 'you', text: msg }])
    try {
      const data = await api.platformChat(`${msg} (chart ${symbol})`)
      setChatLog((rows) => [...rows, { who: 'dexter', text: data.text || data.response || '' }])
    } catch (e) {
      setChatLog((rows) => [...rows, { who: 'dexter', text: `(offline) ${e.message}` }])
    }
  }

  const submit = async (direction) => {
    setTicket('Submitting…')
    try {
      const data = await api.platformExecute({ symbol, direction, size: Number(size) || 1, venue })
      setTicket(
        `${data.status}  ${data.direction || direction} ${data.symbol} x${data.size} @ ${data.venue}  ${
          data.dry_run ? 'DRY-RUN' : 'LIVE'
        }`,
      )
      load()
    } catch (e) {
      setTicket(`Order failed: ${e.message}`)
    }
  }

  const components = status?.components || []
  const cards = desk?.venue_cards || []
  const blotter = desk?.paper_trades || []
  const controllers = inventory?.hummingbot_controllers || []
  const skills = inventory?.vibe_skills || []
  const brainMode = brain?.mode === 'cli-subprocess-only'

  return (
    <div className="-m-0 min-h-[calc(100vh-0px)] bg-[#0b0d10] text-[#d7dde5] font-mono text-[13px] rounded-xl overflow-hidden border border-[#1f2a36]">
      <div className="flex items-center justify-between px-4 py-3 border-b border-[#1f2a36]">
        <div>
          <div className="text-sm tracking-widest uppercase text-[#9ecbff]">Alpha Trader Desk</div>
          <div className="text-[11px] text-[#8b9bb4]">
            {desk?.ok ? 'DEXTER ONLINE' : 'DEXTER'} · {desk?.dry_run ? 'DRY-RUN' : 'LIVE GATE'} · brain{' '}
            {brainMode ? 'CLI subprocess only' : '…'} · no cloud API keys
          </div>
        </div>
        <button
          onClick={launchFincept}
          className="flex items-center gap-2 bg-[#1a4d8c] hover:bg-[#2563b8] text-white text-xs px-3 py-1.5 rounded"
        >
          <IconDeviceDesktop className="w-4 h-4" /> Open Fincept (local)
        </button>
      </div>

      {error ? <div className="px-4 py-2 text-red text-xs">{error}</div> : null}
      {finceptMsg ? <div className="px-4 py-1 text-[11px] text-[#8b9bb4]">Fincept: {finceptMsg}</div> : null}

      <div className="flex gap-2 px-3 py-2 overflow-x-auto border-b border-[#1f2a36]">
        {cards.map((v) => (
          <button
            key={v.id}
            onClick={() => {
              setVenue(v.id)
              if (v.symbol) pickSymbol(v.symbol)
            }}
            className={`shrink-0 border px-3 py-1.5 text-[11px] ${
              venue === v.id ? 'border-[#9ecbff] text-[#9ecbff]' : 'border-[#1f2a36] text-[#8b9bb4]'
            }`}
          >
            {v.name} · {v.connected ? 'ON' : 'OFF'}
          </button>
        ))}
      </div>

      <div className="grid md:grid-cols-5 gap-2 p-3">
        {components.map((c) => (
          <div key={c.id} className="border border-[#1f2a36] rounded p-3 bg-[#10151c]">
            <div className="flex items-center gap-2 mb-1">
              <Dot ok={c.ok} />
              <span className="text-xs font-semibold">{c.name}</span>
            </div>
            <div className="text-[11px] text-[#8b9bb4]">{c.role}</div>
          </div>
        ))}
      </div>

      <div className="grid lg:grid-cols-[220px_1fr_320px] gap-3 px-3 pb-3">
        <Panel title="Watchlist" icon={IconChartCandle}>
          <div className="max-h-[280px] overflow-auto">
            {quotes.map((q) => (
              <button
                key={q.symbol}
                onClick={() => pickSymbol(q.symbol)}
                className="w-full flex justify-between gap-2 py-1 text-left hover:text-[#9ecbff]"
              >
                <span>{q.symbol}</span>
                <span className={q.change >= 0 ? 'text-[#26a69a]' : 'text-[#ef5350]'}>
                  {Number(q.price || 0).toFixed(2)}
                </span>
              </button>
            ))}
          </div>
        </Panel>

        <Panel title={`Chart  ·  ${symbol}`} icon={IconChartCandle} className="min-h-[280px]">
          <div className="flex gap-2 mb-2">
            <input
              value={symbol}
              onChange={(e) => setSymbol(e.target.value.toUpperCase())}
              onKeyDown={(e) => e.key === 'Enter' && pickSymbol(symbol)}
              className="w-28 bg-[#0b0d10] border border-[#1f2a36] rounded px-2 py-1 text-xs"
            />
            <button onClick={() => pickSymbol(symbol)} className="border border-[#1f2a36] px-2 text-[11px]">
              LOAD
            </button>
          </div>
          <CandleChart candles={candles} symbol={symbol} />
        </Panel>

        <div className="space-y-3">
          <Panel title="Order">
            <div className="grid grid-cols-2 gap-2 mb-2">
              <label className="text-[11px] text-[#8b9bb4]">
                Venue
                <select
                  value={venue}
                  onChange={(e) => setVenue(e.target.value)}
                  className="block w-full bg-[#0b0d10] border border-[#1f2a36] rounded px-2 py-1 mt-1"
                >
                  {(cards.length ? cards : [{ id: 'paper', name: 'Paper' }]).map((v) => (
                    <option key={v.id} value={v.id}>
                      {v.name}
                    </option>
                  ))}
                </select>
              </label>
              <label className="text-[11px] text-[#8b9bb4]">
                Size
                <input
                  type="number"
                  min="1"
                  value={size}
                  onChange={(e) => setSize(e.target.value)}
                  className="block w-full bg-[#0b0d10] border border-[#1f2a36] rounded px-2 py-1 mt-1"
                />
              </label>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <button onClick={() => submit('long')} className="bg-[#26a69a] text-[#04120f] font-bold py-2">
                BUY
              </button>
              <button onClick={() => submit('short')} className="bg-[#ef5350] text-[#1a0505] font-bold py-2">
                SELL
              </button>
            </div>
            <div className="text-[11px] text-[#8b9bb4] mt-2">{ticket}</div>
          </Panel>

          <Panel title="Dexter brain" icon={IconBrain}>
            <div className="text-[11px] text-[#8b9bb4] mb-2">
              {brain?.gizzi_cli ? 'gizzi' : 'no gizzi'} · {brain?.kimi_cli ? 'kimi CLI' : 'no kimi'} ·{' '}
              {brain?.omlx ? `omlx ${brain.omlx_model}` : 'omlx down'} · {brain?.brain_path || 'no ~/brain'}
            </div>
            <div className="h-28 overflow-auto text-[12px] mb-2 space-y-1">
              {chatLog.map((row, i) => (
                <div key={i}>
                  <span className="text-[#8b9bb4]">{row.who}</span> {row.text}
                </div>
              ))}
            </div>
            <input
              value={chatInput}
              onChange={(e) => setChatInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && sendChat()}
              placeholder="ask Dexter — gizzi/kimi subprocess, no API keys"
              className="w-full bg-[#0b0d10] border border-[#1f2a36] rounded px-2 py-1.5 text-xs"
            />
          </Panel>
        </div>
      </div>

      <div className="grid lg:grid-cols-2 gap-3 px-3 pb-3">
        <Panel title="Paper blotter">
          <div className="max-h-40 overflow-auto">
            <table className="w-full text-[11px]">
              <thead className="text-[#8b9bb4]">
                <tr>
                  <th className="text-left">time</th>
                  <th className="text-left">sym</th>
                  <th className="text-left">side</th>
                  <th className="text-left">src</th>
                </tr>
              </thead>
              <tbody>
                {blotter.slice(-12).map((row, i) => (
                  <tr key={i}>
                    <td>{String(row.timestamp || '').slice(11, 19)}</td>
                    <td>{row.symbol}</td>
                    <td>{row.direction}</td>
                    <td>{row.source}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
        <Panel title="News">
          <div className="max-h-40 overflow-auto space-y-1 text-[12px]">
            {news.map((a) => (
              <div key={a.id || a.headline} className="truncate" title={a.summary}>
                {a.headline}
              </div>
            ))}
          </div>
        </Panel>
        <Panel title="Hummingbot catalog" icon={IconChartCandle}>
          <div className="text-[11px] text-[#8b9bb4] mb-2">
            {controllers.length} controllers · live start disabled
          </div>
          <div className="max-h-40 overflow-auto space-y-1">
            {controllers.slice(0, 16).map((item) => (
              <div key={item.path} className="flex justify-between gap-2">
                <span>{item.id}</span>
                <span className="text-[#8b9bb4]">{item.group}</span>
              </div>
            ))}
          </div>
        </Panel>
        <Panel title="AutoHedge" icon={IconAffiliate}>
          <input
            value={task}
            onChange={(e) => setTask(e.target.value)}
            className="w-full bg-[#0b0d10] border border-[#1f2a36] rounded px-2 py-1.5 mb-2 text-xs"
          />
          <button
            onClick={runHedge}
            disabled={busy}
            className="flex items-center gap-2 bg-[#16351f] hover:bg-[#1f4d2a] text-[#7dffa3] text-xs px-3 py-1.5 rounded disabled:opacity-50"
          >
            <IconPlayerPlay className="w-3.5 h-3.5" />
            {busy ? 'Running…' : 'Run director cycle'}
          </button>
          {hedge ? (
            <pre className="mt-2 max-h-32 overflow-auto text-[11px] text-[#8b9bb4] whitespace-pre-wrap">
              {JSON.stringify(hedge, null, 2).slice(0, 1800)}
            </pre>
          ) : null}
        </Panel>
        <Panel title="Vibe skills" icon={IconBrain}>
          <div className="max-h-40 overflow-auto grid grid-cols-2 gap-x-3 gap-y-1 text-[12px]">
            {skills.slice(0, 24).map((s) => (
              <div key={s.id} className="truncate">
                {s.id}
              </div>
            ))}
          </div>
        </Panel>
      </div>
    </div>
  )
}
