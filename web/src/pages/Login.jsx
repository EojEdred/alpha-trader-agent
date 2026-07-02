import { useState } from 'react'
import { IconCircleDot, IconLoader2 } from '@tabler/icons-react'
import { useAlphaTrader } from '../context/WebSocketContext'

export default function Login() {
  const { login, checkingAuth } = useAlphaTrader()
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const handleSubmit = async (e) => {
    e.preventDefault()
    setLoading(true)
    setError('')
    try {
      const ok = await login(password)
      if (!ok) setError('Invalid password')
    } catch (e) {
      setError(e.message || 'Login failed')
    } finally {
      setLoading(false)
    }
  }

  if (checkingAuth) {
    return (
      <div className="min-h-screen bg-bg flex items-center justify-center">
        <IconLoader2 className="w-8 h-8 text-blue animate-spin" />
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-bg flex items-center justify-center p-4">
      <div className="w-full max-w-sm bg-panel border border-border rounded-xl p-8 shadow-2xl">
        <div className="flex justify-center mb-6">
          <div className="w-14 h-14 rounded-full bg-blue/10 flex items-center justify-center">
            <IconCircleDot className="w-8 h-8 text-blue" />
          </div>
        </div>
        <h1 className="text-2xl font-bold text-center mb-1">Alpha Trader</h1>
        <p className="text-dim text-center text-sm mb-6">Command Center</p>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-xs font-medium text-dim mb-1.5 uppercase tracking-wide">
              Password
            </label>
            <input
              id="login-password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Enter password"
              className="w-full bg-bg border border-border rounded-lg px-4 py-2.5 text-sm text-text placeholder:text-dim/50 focus:outline-none focus:border-blue focus:ring-1 focus:ring-blue"
              autoFocus
            />
          </div>
          {error && <div className="text-red text-sm">{error}</div>}
          <button
            id="login-btn"
            type="submit"
            disabled={loading || !password}
            className="w-full bg-blue hover:bg-blue/90 disabled:opacity-50 disabled:cursor-not-allowed text-white font-semibold py-2.5 rounded-lg transition-colors flex items-center justify-center gap-2"
          >
            {loading && <IconLoader2 className="w-4 h-4 animate-spin" />}
            Enter
          </button>
        </form>
      </div>
    </div>
  )
}
