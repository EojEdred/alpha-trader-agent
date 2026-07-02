import { createContext, useContext, useEffect, useRef, useState, useCallback } from 'react'
import { api } from '../lib/api'

const WebSocketContext = createContext(null)

export function useAlphaTrader() {
  return useContext(WebSocketContext)
}

export function AlphaTraderProvider({ children }) {
  const [authenticated, setAuthenticated] = useState(false)
  const [checkingAuth, setCheckingAuth] = useState(true)
  const [connected, setConnected] = useState(false)
  const [status, setStatus] = useState({})
  const [trades, setTrades] = useState([])
  const [agents, setAgents] = useState([])
  const [risk, setRisk] = useState({})
  const [positions, setPositions] = useState({})
  const [pending, setPending] = useState([])
  const [pnl, setPnl] = useState({})
  const [reports, setReports] = useState([])
  const [workflows, setWorkflows] = useState([])
  const [logs, setLogs] = useState([])
  const [chatMessages, setChatMessages] = useState([])
  const [error, setError] = useState(null)

  const wsRef = useRef(null)
  const reconnectTimeoutRef = useRef(null)
  const intentionalCloseRef = useRef(false)

  const checkAuth = useCallback(async () => {
    try {
      const me = await api.me()
      setAuthenticated(me.authenticated)
      return me.authenticated
    } catch (e) {
      setAuthenticated(false)
      return false
    } finally {
      setCheckingAuth(false)
    }
  }, [])

  const connectWebSocket = useCallback(() => {
    if (wsRef.current || !authenticated) return
    intentionalCloseRef.current = false
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const ws = new WebSocket(`${protocol}//${window.location.host}/ws`)
    wsRef.current = ws

    ws.onopen = () => {
      setConnected(true)
      setError(null)
    }

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        if (data.type === 'state') {
          if (data.status) setStatus(data.status)
          if (data.trades) setTrades(data.trades)
          if (data.agents) setAgents(data.agents)
          if (data.risk) setRisk(data.risk)
          if (data.positions) setPositions(data.positions)
          if (data.pending) setPending(data.pending)
          if (data.pnl) setPnl(data.pnl)
          if (data.reports) setReports(data.reports)
          if (data.workflows) setWorkflows(data.workflows)
          if (data.logs) setLogs(data.logs)
        } else if (data.type === 'log') {
          setLogs((prev) => {
            const next = [...prev, data.log]
            if (next.length > 500) next.shift()
            return next
          })
        } else if (data.type === 'chat') {
          setChatMessages((prev) => [...prev, { role: 'assistant', text: data.text, time: Date.now() }])
        }
      } catch (e) {
        console.error('WS parse error', e)
      }
    }

    ws.onerror = () => {
      setConnected(false)
    }

    ws.onclose = () => {
      wsRef.current = null
      setConnected(false)
      if (!intentionalCloseRef.current && authenticated) {
        reconnectTimeoutRef.current = setTimeout(connectWebSocket, 3000)
      }
    }
  }, [authenticated])

  const disconnectWebSocket = useCallback(() => {
    intentionalCloseRef.current = true
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current)
      reconnectTimeoutRef.current = null
    }
    if (wsRef.current) {
      wsRef.current.close()
      wsRef.current = null
    }
  }, [])

  useEffect(() => {
    checkAuth()
  }, [checkAuth])

  useEffect(() => {
    if (authenticated) {
      connectWebSocket()
    } else {
      disconnectWebSocket()
    }
    return () => disconnectWebSocket()
  }, [authenticated, connectWebSocket, disconnectWebSocket])

  const login = async (password) => {
    await api.login(password)
    const ok = await checkAuth()
    return ok
  }

  const logout = async () => {
    try {
      await api.logout()
    } finally {
      setAuthenticated(false)
      setStatus({})
      setTrades([])
      setAgents([])
      setRisk({})
      setPositions({})
      setPending([])
      setPnl({})
      setReports([])
      setWorkflows([])
      setLogs([])
      setChatMessages([])
    }
  }

  const sendCommand = async (name, ...args) => {
    try {
      if (name === 'control') {
        const res = await api.control(args[0])
        return res
      }
      if (name === 'trade') {
        return await api.trade(args[0])
      }
      if (name === 'approve') {
        return await api.approve(args[0])
      }
      if (name === 'reject') {
        return await api.reject(args[0])
      }
      if (name === 'runWorkflow') {
        return await api.runWorkflow(args[0])
      }
      if (name === 'chat') {
        const message = args[0]
        setChatMessages((prev) => [...prev, { role: 'user', text: message, time: Date.now() }])
        const res = await api.chat(message)
        setChatMessages((prev) => [...prev, { role: 'assistant', text: res.text || res.response, time: Date.now() }])
        return res
      }
      if (name === 'serviceRestart') {
        return await api.serviceRestart()
      }
    } catch (e) {
      setError(e.message)
      throw e
    }
  }

  const value = {
    authenticated,
    checkingAuth,
    connected,
    status,
    trades,
    agents,
    risk,
    positions,
    pending,
    pnl,
    reports,
    workflows,
    logs,
    chatMessages,
    error,
    login,
    logout,
    sendCommand,
    refresh: checkAuth,
  }

  return <WebSocketContext.Provider value={value}>{children}</WebSocketContext.Provider>
}
