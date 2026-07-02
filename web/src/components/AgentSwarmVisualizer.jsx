import { useState, useEffect, useRef } from 'react'
import { IconRobot, IconActivity, IconList, IconNetwork, IconTerminal, IconAlertCircle } from '@tabler/icons-react'
import { cn, formatTime, statusColor } from '../lib/utils'

export default function AgentSwarmVisualizer({ agents }) {
  const [viewMode, setViewMode] = useState('swarm') // 'swarm' or 'list'
  const [activeLogs, setActiveLogs] = useState([])
  const prevAgentsRef = useRef([])

  // Watch agent status changes to generate live "Swarm Event Log" messages
  useEffect(() => {
    if (!agents || agents.length === 0) return

    const logs = []
    agents.forEach((agent) => {
      const prev = prevAgentsRef.current.find((p) => p.name === agent.name)
      if (prev && (prev.status !== agent.status || prev.last_action !== agent.last_action)) {
        if (agent.last_action) {
          logs.push({
            id: Math.random().toString(36).substr(2, 9),
            time: new Date().toLocaleTimeString(),
            agent: agent.name,
            status: agent.status,
            action: agent.last_action,
          })
        }
      }
    })

    if (logs.length > 0) {
      setActiveLogs((prev) => {
        const next = [...logs, ...prev]
        return next.slice(0, 50) // keep last 50 entries
      })
    }

    prevAgentsRef.current = agents
  }, [agents])

  if (!agents || agents.length === 0) {
    return (
      <div className="bg-panel border border-border rounded-xl p-8 text-center text-dim text-sm">
        No agents registered
      </div>
    )
  }

  // Calculate coordinates for SVGs dynamically
  const width = 600
  const height = 360
  const cx = width / 2
  const cy = height / 2
  const r = 110 // Orbit radius

  const getCoordinates = (index, total) => {
    const angle = (index * 2 * Math.PI) / total - Math.PI / 2 // offset by 90deg to start at top
    return {
      x: cx + r * Math.cos(angle),
      y: cy + r * Math.sin(angle),
    }
  }

  return (
    <div className="bg-panel border border-border rounded-xl p-5 shadow-2xl relative overflow-hidden">
      {/* Component Styles for Glowing Rings and SVG Link Flows */}
      <style>{`
        @keyframes swarm-dash {
          to {
            stroke-dashoffset: -40;
          }
        }
        @keyframes swarm-pulse {
          0% { transform: scale(0.9); opacity: 0.3; }
          50% { transform: scale(1.15); opacity: 0.8; }
          100% { transform: scale(0.9); opacity: 0.3; }
        }
        @keyframes swarm-spin {
          100% { transform: rotate(360deg); }
        }
        .swarm-link-active {
          stroke-dasharray: 8, 4;
          animation: swarm-dash 1.5s linear infinite;
        }
        .swarm-node-pulse {
          animation: swarm-pulse 2s infinite ease-in-out;
        }
        .swarm-ring-spin {
          transform-origin: center;
          animation: swarm-spin 10s linear infinite;
        }
      `}</style>

      {/* Header controls */}
      <div className="flex items-center justify-between border-b border-border pb-4 mb-5">
        <div className="flex items-center gap-2">
          <IconActivity className="w-5 h-5 text-blue animate-pulse" />
          <div>
            <h3 className="font-bold text-sm">Swarm Operations</h3>
            <p className="text-[10px] text-dim uppercase tracking-wider">Real-time collaboration network</p>
          </div>
        </div>
        
        <div className="flex bg-bg rounded-lg p-0.5 border border-border">
          <button
            onClick={() => setViewMode('swarm')}
            className={cn(
              'flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-md transition-all',
              viewMode === 'swarm' ? 'bg-panel text-blue shadow-sm' : 'text-dim hover:text-text'
            )}
          >
            <IconNetwork className="w-3.5 h-3.5" />
            Live Swarm Map
          </button>
          <button
            onClick={() => setViewMode('list')}
            className={cn(
              'flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-md transition-all',
              viewMode === 'list' ? 'bg-panel text-blue shadow-sm' : 'text-dim hover:text-text'
            )}
          >
            <IconList className="w-3.5 h-3.5" />
            List View
          </button>
        </div>
      </div>

      {viewMode === 'list' ? (
        /* Original list grid view */
        <div className="grid gap-3 grid-cols-2 md:grid-cols-3 lg:grid-cols-4">
          {agents.map((a) => {
            const color = statusColor(a.status)
            return (
              <div
                key={a.name}
                className="bg-bg border border-border rounded-xl p-4 hover:border-border/80 transition-colors"
              >
                <div className="flex items-start justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <div className={cn('p-1.5 rounded-md', 
                      color === 'green' && 'bg-green/10 text-green', 
                      color === 'yellow' && 'bg-yellow/10 text-yellow', 
                      color === 'red' && 'bg-red/10 text-red',
                      color === 'dim' && 'bg-dim/10 text-dim'
                    )}>
                      <IconRobot className="w-4 h-4" />
                    </div>
                    <span className="font-semibold text-sm truncate max-w-[100px]" title={a.name}>
                      {a.name}
                    </span>
                  </div>
                  <span className={cn('text-[9px] font-bold uppercase tracking-wider', 
                    color === 'green' && 'text-green',
                    color === 'yellow' && 'text-yellow',
                    color === 'red' && 'text-red',
                    color === 'dim' && 'text-dim'
                  )}>
                    {a.status}
                  </span>
                </div>
                <div className="text-xs text-dim truncate" title={a.last_action}>
                  {a.last_action || 'idle'}
                </div>
                {a.error && (
                  <div className="text-[10px] text-red mt-2 flex items-center gap-1">
                    <IconAlertCircle className="w-3.5 h-3.5" />
                    <span className="truncate">{a.error}</span>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      ) : (
        /* Animated Graph Swarm Map */
        <div className="grid lg:grid-cols-3 gap-5">
          {/* SVG Swarm Canvas */}
          <div className="lg:col-span-2 bg-bg/50 border border-border rounded-xl flex items-center justify-center p-2 relative h-[380px]">
            {/* Background Grid Lines */}
            <div className="absolute inset-0 bg-[linear-gradient(to_right,#1f2937_1px,transparent_1px),linear-gradient(to_bottom,#1f2937_1px,transparent_1px)] bg-[size:24px_24px] opacity-15" />
            
            <svg width="100%" height="100%" viewBox={`0 0 ${width} ${height}`} className="z-10 overflow-visible">
              {/* Dynamic Connection Lines */}
              {agents.map((a, idx) => {
                const { x, y } = getCoordinates(idx, agents.length)
                const isActive = a.status === 'busy' || a.status === 'thinking'
                const isError = a.status === 'error'
                
                return (
                  <g key={`links-${a.name}`}>
                    {/* Path from Central controller to agent */}
                    <line
                      x1={cx}
                      y1={cy}
                      x2={x}
                      y2={y}
                      stroke={isError ? '#ef4444' : isActive ? '#3b82f6' : '#1f2937'}
                      strokeWidth={isActive ? '2' : '1'}
                      className={cn(isActive && 'swarm-link-active')}
                    />
                    
                    {/* Ring-flow around neighbors to demonstrate swarm loops */}
                    {idx < agents.length - 1 && (
                      <path
                        d={`M ${x} ${y} Q ${cx} ${cy} ${getCoordinates(idx + 1, agents.length).x} ${getCoordinates(idx + 1, agents.length).y}`}
                        fill="none"
                        stroke={isActive ? '#3b82f6' : '#1f2937'}
                        strokeWidth="1"
                        strokeDasharray="4,4"
                        opacity="0.3"
                      />
                    )}
                  </g>
                )
              })}

              {/* Central Controller Node (The Orchestrator) */}
              <g transform={`translate(${cx}, ${cy})`}>
                <circle r="36" fill="#111827" stroke="#1f2937" strokeWidth="2" />
                <circle r="46" fill="none" stroke="#3b82f6" strokeWidth="1" strokeDasharray="6,4" className="swarm-ring-spin" opacity="0.3" />
                <circle r="30" fill="none" stroke="#3b82f6" strokeWidth="2" opacity="0.5" className="swarm-node-pulse" />
                <foreignObject x="-20" y="-20" width="40" height="40">
                  <div className="w-full h-full flex items-center justify-center text-blue">
                    <IconActivity className="w-6 h-6 animate-pulse" />
                  </div>
                </foreignObject>
                <text y="48" textAnchor="middle" fill="#9ca3af" className="text-[9px] font-bold uppercase tracking-widest font-mono">
                  Orchestrator
                </text>
              </g>

              {/* Dynamic Agent Nodes */}
              {agents.map((a, idx) => {
                const { x, y } = getCoordinates(idx, agents.length)
                const color = statusColor(a.status)
                const isBusy = a.status === 'busy' || a.status === 'thinking'
                const isError = a.status === 'error'

                return (
                  <g key={a.name} transform={`translate(${x}, ${y})`}>
                    {/* Outer glowing pulsing ring for busy agents */}
                    {isBusy && (
                      <circle r="32" fill="none" stroke="#3b82f6" strokeWidth="3" className="swarm-node-pulse" />
                    )}
                    
                    {/* Base Node */}
                    <circle r="22" fill="#111827" stroke={isError ? '#ef4444' : isBusy ? '#3b82f6' : '#1f2937'} strokeWidth="2" />
                    
                    {/* Spinning ring on busy */}
                    {isBusy && (
                      <circle r="26" fill="none" stroke="#3b82f6" strokeWidth="1.5" strokeDasharray="8,4" className="swarm-ring-spin" />
                    )}
                    
                    {/* Center Icon */}
                    <foreignObject x="-12" y="-12" width="24" height="24">
                      <div className={cn(
                        'w-full h-full flex items-center justify-center rounded-full transition-colors',
                        color === 'green' && 'text-green bg-green/10',
                        color === 'yellow' && 'text-yellow bg-yellow/10',
                        color === 'red' && 'text-red bg-red/10',
                        color === 'dim' && 'text-dim bg-dim/10'
                      )}>
                        <IconRobot className={cn('w-4 h-4', isBusy && 'animate-bounce')} />
                      </div>
                    </foreignObject>

                    {/* Agent Name Tag */}
                    <text y="32" textAnchor="middle" fill="#e5e7eb" className="text-[10px] font-bold font-mono">
                      {a.name.replace('Agent', '').replace('Manager', '')}
                    </text>

                    {/* Miniature status badge */}
                    <circle cx="16" cy="-16" r="5" fill={color === 'green' ? '#22c55e' : color === 'yellow' ? '#eab308' : color === 'red' ? '#ef4444' : '#9ca3af'} />
                    
                    {/* Mini details card display on hover */}
                    <title>{`${a.name}\nStatus: ${a.status}\nTask: ${a.last_action || 'idle'}`}</title>
                  </g>
                )
              })}
            </svg>

            {/* Active tooltips floating inside canvas */}
            <div className="absolute bottom-3 left-3 bg-panel/90 backdrop-blur border border-border px-3 py-1.5 rounded-lg shadow-lg z-20 max-w-[200px]">
              <span className="text-[9px] font-bold uppercase tracking-wider text-dim block">Active Task Target</span>
              <span className="text-xs font-mono font-semibold truncate block mt-0.5">
                {agents.find((a) => a.status === 'busy' || a.status === 'thinking')?.name || 'Listening for signals...'}
              </span>
            </div>
          </div>

          {/* Real-time Collaboration Feed Panel */}
          <div className="bg-bg/40 border border-border rounded-xl p-4 flex flex-col h-[380px]">
            <div className="flex items-center gap-1.5 text-xs font-bold uppercase tracking-wide text-dim border-b border-border/60 pb-2 mb-3">
              <IconTerminal className="w-4 h-4 text-blue" />
              Swarm Live Feed
            </div>
            
            <div className="flex-1 overflow-y-auto space-y-2.5 pr-1 font-mono text-[11px] leading-normal">
              {activeLogs.length > 0 ? (
                activeLogs.map((log) => (
                  <div key={log.id} className="border-l border-border/60 pl-2 py-0.5 space-y-0.5">
                    <div className="flex items-center justify-between text-dim">
                      <span className="text-blue font-bold truncate max-w-[120px]">{log.agent}</span>
                      <span>{log.time}</span>
                    </div>
                    <p className="text-text/90 italic">{log.action}</p>
                  </div>
                ))
              ) : (
                <div className="h-full flex flex-col items-center justify-center text-center text-dim/60 px-4 space-y-2 py-12">
                  <IconTerminal className="w-8 h-8 opacity-30" />
                  <p>Awaiting operations activity... Start a manual cycle or wait for market triggers.</p>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
