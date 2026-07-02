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
} from '@tabler/icons-react'
import { useAlphaTrader } from '../context/WebSocketContext'
import { cn, formatDuration } from '../lib/utils'

const navItems = [
  { to: '/', label: 'Dashboard', icon: IconLayoutDashboard },
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
      <aside className="w-60 bg-panel border-r border-border flex flex-col">
        <div className="h-14 flex items-center px-5 border-b border-border">
          <IconCircleDot className="w-6 h-6 text-blue mr-2" />
          <div>
            <div className="font-bold leading-tight">Alpha Trader</div>
            <div className="text-[10px] text-dim uppercase tracking-wide">Command Center</div>
          </div>
        </div>

        <nav className="flex-1 overflow-y-auto py-3 px-2 space-y-1">
          {navItems.map((item) => {
            const Icon = item.icon
            const active = location.pathname === item.to
            return (
              <NavLink
                key={item.to}
                to={item.to}
                className={cn(
                  'flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-colors',
                  active
                    ? 'bg-blue/10 text-blue font-medium'
                    : 'text-dim hover:bg-panel-hover hover:text-text'
                )}
              >
                <Icon className="w-[18px] h-[18px]" />
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
            <IconLogout className="w-[18px] h-[18px]" />
            Logout
          </button>
        </div>
      </aside>

      <div className="flex-1 flex flex-col min-w-0">
        <header className="h-14 bg-panel border-b border-border flex items-center justify-between px-5 shrink-0">
          <div className="flex items-center gap-3">
            <h1 className="text-sm font-medium text-dim uppercase tracking-wide">
              {navItems.find((n) => n.to === location.pathname)?.label || 'Dashboard'}
            </h1>
          </div>
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2">
              <span
                className={cn(
                  'w-2 h-2 rounded-full animate-pulse-dot',
                  connected ? 'bg-green' : 'bg-red'
                )}
              />
              <span className="text-xs text-dim">{connected ? 'Live' : 'Reconnecting'}</span>
            </div>
            <span
              className={cn(
                'px-2.5 py-1 rounded text-[11px] font-bold uppercase tracking-wide',
                mode === 'running' && 'bg-green/10 text-green',
                mode === 'paused' && 'bg-yellow/10 text-yellow',
                mode === 'stopped' && 'bg-dim/10 text-dim',
                mode === 'error' && 'bg-red/10 text-red'
              )}
            >
              {mode}
            </span>
            <span className="px-2.5 py-1 rounded text-[11px] font-bold uppercase tracking-wide bg-dim/10 text-dim">
              {status.dry_run ? 'Dry Run' : 'Live'}
            </span>
            <span className="text-xs text-dim">uptime {formatDuration(status.uptime_seconds)}</span>
          </div>
        </header>

        <main className="flex-1 overflow-y-auto p-5">{children}</main>
      </div>
    </div>
  )
}
