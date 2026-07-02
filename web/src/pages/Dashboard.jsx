import {
  IconPlayerPlay,
  IconBuildingBank,
  IconRobot,
  IconTrendingUp,
  IconActivity,
  IconShieldCheck,
} from '@tabler/icons-react'
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts'
import { useAlphaTrader } from '../context/WebSocketContext'
import StatCard from '../components/StatCard'
import TradeTable from '../components/TradeTable'
import AgentSwarmVisualizer from '../components/AgentSwarmVisualizer'
import StatusBadge from '../components/StatusBadge'

import { formatCurrency, formatDuration } from '../lib/utils'

export default function Dashboard() {
  const { status, trades, agents, risk, pnl } = useAlphaTrader()

  const chartData = trades
    .slice()
    .reverse()
    .reduce((acc, t) => {
      const last = acc.length ? acc[acc.length - 1].pnl : 0
      acc.push({ time: new Date(t.timestamp).toLocaleTimeString(), pnl: last + (t.pnl || 0) })
      return acc
    }, [])

  return (
    <div className="space-y-5">
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <StatCard
          label="Mode"
          value={status.mode?.toUpperCase() || 'STOPPED'}
          subtext={`uptime ${formatDuration(status.uptime_seconds)}`}
          icon={IconPlayerPlay}
          color={status.mode === 'running' ? 'green' : status.mode === 'paused' ? 'yellow' : 'dim'}
        />
        <StatCard
          label="Active Venues"
          value={(status.active_venues || []).length}
          subtext={(status.active_venues || []).join(', ')}
          icon={IconBuildingBank}
          color="blue"
        />
        <StatCard
          label="Agents"
          value={agents.length}
          subtext={`${agents.filter((a) => a.status === 'idle' || a.status === 'busy').length} online`}
          icon={IconRobot}
          color="blue"
        />
        <StatCard
          label="Total P&L"
          value={formatCurrency(pnl.total_pnl)}
          subtext={`${pnl.wins || 0} wins / ${pnl.losses || 0} losses`}
          icon={IconTrendingUp}
          color={(pnl.total_pnl || 0) >= 0 ? 'green' : 'red'}
        />
      </div>

      <div className="grid gap-5 lg:grid-cols-3">
        <div className="lg:col-span-2 bg-panel border border-border rounded-xl p-5">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-xs font-bold uppercase tracking-wide text-dim">Equity Curve</h3>
            <StatusBadge status={risk.circuit_breaker_active ? 'active' : 'ok'} />
          </div>
          <div className="h-64">
            {chartData.length > 1 ? (
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={chartData}>
                  <defs>
                    <linearGradient id="colorPnl" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#22c55e" stopOpacity={0.3} />
                      <stop offset="95%" stopColor="#22c55e" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
                  <XAxis dataKey="time" stroke="#6b7280" fontSize={10} tickLine={false} />
                  <YAxis stroke="#6b7280" fontSize={10} tickLine={false} tickFormatter={(v) => `$${v}`} />
                  <Tooltip
                    contentStyle={{ backgroundColor: '#111827', borderColor: '#1f2937', color: '#e5e7eb' }}
                    itemStyle={{ color: '#22c55e' }}
                    formatter={(v) => formatCurrency(v)}
                  />
                  <Area type="monotone" dataKey="pnl" stroke="#22c55e" fillOpacity={1} fill="url(#colorPnl)" />
                </AreaChart>
              </ResponsiveContainer>
            ) : (
              <div className="h-full flex items-center justify-center text-dim text-sm">
                Submit a trade to see the equity curve
              </div>
            )}
          </div>
        </div>

        <div className="bg-panel border border-border rounded-xl p-5">
          <h3 className="text-xs font-bold uppercase tracking-wide text-dim mb-4">Risk Snapshot</h3>
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <span className="text-sm text-dim">Circuit breaker</span>
              <StatusBadge status={risk.circuit_breaker_active ? 'active' : 'ok'} />
            </div>
            <div className="flex items-center justify-between">
              <span className="text-sm text-dim">Consecutive losses</span>
              <span className="font-semibold">{risk.consecutive_losses || 0}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-sm text-dim">Daily trades</span>
              <span className="text-xs font-mono text-dim">{JSON.stringify(risk.daily_trades || {})}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-sm text-dim">Rate limited</span>
              <span className="text-xs font-mono text-dim">{JSON.stringify(risk.rate_limited || {})}</span>
            </div>
          </div>

          <div className="mt-6 pt-6 border-t border-border">
            <h3 className="text-xs font-bold uppercase tracking-wide text-dim mb-3">System Health</h3>
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-lg bg-green/10 text-green flex items-center justify-center">
                <IconShieldCheck className="w-5 h-5" />
              </div>
              <div>
                <div className="text-sm font-medium">All systems operational</div>
                <div className="text-xs text-dim">Dry-run mode active</div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="bg-panel border border-border rounded-xl p-5">
        <h3 className="text-xs font-bold uppercase tracking-wide text-dim mb-4">Recent Trades</h3>
        <TradeTable trades={trades.slice(0, 5)} compact />
      </div>

      <AgentSwarmVisualizer agents={agents} />

    </div>
  )
}
