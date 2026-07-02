import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { AlphaTraderProvider, useAlphaTrader } from './context/WebSocketContext'
import Layout from './components/Layout'
import Login from './pages/Login'
import Dashboard from './pages/Dashboard'
import Trades from './pages/Trades'
import Positions from './pages/Positions'
import Pending from './pages/Pending'
import Chat from './pages/Chat'
import Logs from './pages/Logs'
import Reports from './pages/Reports'
import Control from './pages/Control'
import Settings from './pages/Settings'

function AppRoutes() {
  const { authenticated, checkingAuth } = useAlphaTrader()

  if (checkingAuth) {
    return (
      <div className="min-h-screen bg-bg flex items-center justify-center">
        <div className="w-8 h-8 border-2 border-blue border-t-transparent rounded-full animate-spin" />
      </div>
    )
  }

  if (!authenticated) {
    return <Login />
  }

  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/trades" element={<Trades />} />
        <Route path="/positions" element={<Positions />} />
        <Route path="/pending" element={<Pending />} />
        <Route path="/chat" element={<Chat />} />
        <Route path="/logs" element={<Logs />} />
        <Route path="/reports" element={<Reports />} />
        <Route path="/control" element={<Control />} />
        <Route path="/settings" element={<Settings />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Layout>
  )
}


function App() {
  return (
    <AlphaTraderProvider>
      <BrowserRouter>
        <AppRoutes />
      </BrowserRouter>
    </AlphaTraderProvider>
  )
}

export default App
