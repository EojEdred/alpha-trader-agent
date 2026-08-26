import { NavLink, useLocation } from 'react-router-dom'
import {
  IconLayoutDashboard,
  IconArrowsExchange,
  IconBriefcase,
  IconClockPause,
  IconMessageCircle,
  IconFileText,
  IconClipboardList,
  IconPlayerPlay,
  IconLogout,
  IconCircleDot,
  IconSettings,
  IconBrain,
  IconChartBar,
  IconSearch,
  IconRocket,
  IconShieldCheck,
  IconBell,
  IconBuildingBank,
} from '@tabler/icons-react'
import { useAlphaTrader } from '../context/WebSocketContext'
import { cn, formatDuration } from '../lib/utils'

const navItems = [
  { to: '/', label: 'Dashboard', icon: IconLayoutDashboard },
  { to: '/research', label: 'Research', icon: IconBrain },
  { to: '/analysts', label: 'Analysts', icon: IconChartBar },
  { to: '/market-data', label: 'Market Data', icon: IconSearch },
  { to: '/strategies', label: 'Strategies', icon: IconRocket },
  { to: '/signals', label: 'Signals', icon: IconBell },
  { to: '/apex', label: 'Apex', icon: IconBuildingBank },
  { to: '/audit', label: 'Audit', icon: IconShieldCheck },
  { to: '/trades', label: 'Trades', icon: IconArrowsExchange },
  { to: '/positions', label: 'Positions', icon: IconBriefcase },
  { to: '/pending', label: 'Pending', icon: IconClockPause },
  { to: '/chat', label: 'Chat', icon: IconMessageCircle },
  { to: '/logs', label: 'Logs', icon: IconFileText },
  { to: '/reports', label: 'Reports', icon: IconClipboardList },
  { to: '/control', label: 'Control', icon: IconPlayerPlay },
  { to: '/settings', label: 'Settings', icon: IconSettings },
]


export default function Layout({ children }) {
  const { status, connected, authenticated, logout } = useAlphaTrader()
  const location = useLocation()

  if (!authenticated) return children

  const mode = status.mode || 'stopped'

  return (
    <div className="flex h-screen bg-bg text-text overflow-hidden">
      <aside className="w-60 bg-panel border-r border-border flex flex-col shadow-[1px_0_0_rgba(0,0,0,0.03)]">
        <div className="h-14 flex items-center px-5 border-b border-border">
          <div className="w-8 h-8 rounded-xl bg-blue/10 flex items-center justify-center mr-3">
            <IconCircleDot className="w-5 h-5 text-blue" />
          </div>
          <div>
            <div className="font-semibold leading-tight tracking-tight">Alpha Trader</div>
            <div className="text-[10px] text-dim font-medium uppercase tracking-wide">Command Center</div>
          </div>
        </div>

        <nav className="flex-1 overflow-y-auto py-3 px-2.5 space-y-0.5">
          {navItems.map((item) => {
            const Icon = item.icon
            const active = location.pathname === item.to
            return (
              <NavLink
                key={item.to}
                to={item.to}
                className={cn(
                  'flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-all duration-200',
                  active
                    ? 'bg-blue/10 text-blue font-medium shadow-sm'
                    : 'text-dim hover:bg-panel-hover hover:text-text'
                )}
              >
                <Icon className="w-[18px] h-[18px] stroke-[1.75]" />
                {item.label}
              </NavLink>
            )
          })}
        </nav>

        <div className="p-3 border-t border-border">
          <button
            onClick={logout}
            className="flex items-center gap-2 w-full px-3 py-2 text-sm text-dim hover:text-text hover:bg-panel-hover rounded-lg transition-colors"
          >
            <IconLogout className="w-[18px] h-[18px] stroke-[1.75]" />
            Logout
          </button>
        </div>
      </aside>

      <div className="flex-1 flex flex-col min-w-0">
        <header className="h-14 bg-panel/80 backdrop-blur-md border-b border-border flex items-center justify-between px-5 shrink-0">
          <div className="flex items-center gap-3">
            <h1 className="text-sm font-semibold text-text/80 tracking-tight">
              {navItems.find((n) => n.to === location.pathname)?.label || 'Dashboard'}
            </h1>
          </div>
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-2 px-2.5 py-1 rounded-full bg-bg border border-border">
              <span
                className={cn(
                  'w-2 h-2 rounded-full animate-pulse-dot',
                  connected ? 'bg-green' : 'bg-red'
                )}
              />
              <span className="text-xs font-medium text-dim">{connected ? 'Live' : 'Reconnecting'}</span>
            </div>
            <span
              className={cn(
                'px-2.5 py-1 rounded-full text-[11px] font-semibold uppercase tracking-wide border',
                mode === 'running' && 'bg-green/10 text-green border-green/20',
                mode === 'paused' && 'bg-yellow/10 text-yellow border-yellow/20',
                mode === 'stopped' && 'bg-dim/10 text-dim border-dim/20',
                mode === 'error' && 'bg-red/10 text-red border-red/20'
              )}
            >
              {mode}
            </span>
            <span className="px-2.5 py-1 rounded-full text-[11px] font-semibold uppercase tracking-wide bg-bg border border-border text-dim">
              {status.dry_run ? 'Dry Run' : 'Live'}
            </span>
            <span className="text-xs text-dim font-medium">uptime {formatDuration(status.uptime_seconds)}</span>
          </div>
        </header>

        <main className="flex-1 overflow-y-auto p-6">{children}</main>
      </div>
    </div>
  )
}
