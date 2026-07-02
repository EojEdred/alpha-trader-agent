import { useState, useEffect } from 'react'
import {
  IconEye,
  IconEyeOff,
  IconLoader2,
  IconCheck,
  IconAlertCircle,
  IconBrandTelegram,
  IconCpu,
  IconKey,
  IconExchange,
  IconRefresh,
  IconLock,
} from '@tabler/icons-react'
import { api } from '../lib/api'

export default function Settings() {
  const [settings, setSettings] = useState({
    DEXTER_WEB_PASSWORD: '',
    TELEGRAM_BOT_TOKEN: '',
    TELEGRAM_CHAT_ID: '',
    OPENAI_API_KEY: '',
    GEMINI_API_KEY: '',
    LLM_PROVIDER: 'openai',
    BROWSER_USE_MODEL: 'gpt-4o',
    SCHWAB_APP_KEY: '',
    SCHWAB_APP_SECRET: '',
    SCHWAB_REDIRECT_URI: 'https://127.0.0.1:8182/',
    OANDA_API_KEY: '',
    OANDA_ACCOUNT_ID: '',
    KALSHI_API_KEY: '',
    KALSHI_API_SECRET: '',
    TOPSTEP_USERNAME: '',
    TOPSTEP_PASSWORD: '',
  })

  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [restarting, setRestarting] = useState(false)
  const [message, setMessage] = useState(null)
  const [visibleFields, setVisibleFields] = useState({})

  // Fetch settings on mount
  useEffect(() => {
    async function loadSettings() {
      try {
        const data = await api.getSettings()
        if (data && data.settings) {
          setSettings((prev) => ({
            ...prev,
            ...data.settings,
          }))
        }
      } catch (e) {
        setMessage({ type: 'error', text: `Failed to load settings: ${e.message}` })
      } finally {
        setLoading(false)
      }
    }
    loadSettings()
  }, [])

  const handleChange = (key, value) => {
    setSettings((prev) => ({
      ...prev,
      ...{ [key]: value },
    }))
  }

  const toggleVisibility = (key) => {
    setVisibleFields((prev) => ({
      ...prev,
      [key]: !prev[key],
    }))
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    setSaving(true)
    setMessage(null)
    try {
      const res = await api.saveSettings(settings)
      setMessage({ type: 'success', text: res.message || 'Settings saved successfully!' })
    } catch (e) {
      setMessage({ type: 'error', text: `Failed to save: ${e.message}` })
    } finally {
      setSaving(false)
    }
  }

  const handleRestart = async () => {
    if (!window.confirm('Are you sure you want to restart the system service to apply settings? This will disconnect the dashboard temporarily.')) {
      return
    }
    setRestarting(true)
    setMessage(null)
    try {
      await api.serviceRestart()
      setMessage({ type: 'success', text: 'Service restart initiated. The page will reload/reconnect in a few seconds.' })
      setTimeout(() => {
        window.location.reload()
      }, 5000)
    } catch (e) {
      setMessage({ type: 'error', text: `Failed to restart: ${e.message}` })
    } finally {
      setRestarting(false)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <IconLoader2 className="w-8 h-8 text-blue animate-spin" />
      </div>
    )
  }

  const renderInputField = (label, envKey, type = 'text', placeholder = '') => {
    const isSecret = type === 'password'
    const isVisible = visibleFields[envKey]
    const currentType = isSecret && !isVisible ? 'password' : 'text'

    return (
      <div className="space-y-1">
        <label className="block text-xs font-bold uppercase tracking-wider text-dim">{label}</label>
        <div className="relative flex items-center">
          <input
            type={currentType}
            value={settings[envKey] || ''}
            onChange={(e) => handleChange(envKey, e.target.value)}
            placeholder={placeholder}
            className="w-full bg-bg border border-border rounded-lg px-3 py-2 text-sm text-text placeholder:text-dim/30 focus:outline-none focus:border-blue focus:ring-1 focus:ring-blue pr-10"
          />
          {isSecret && (
            <button
              type="button"
              onClick={() => toggleVisibility(envKey)}
              className="absolute right-3 text-dim/50 hover:text-text focus:outline-none"
            >
              {isVisible ? <IconEyeOff className="w-4 h-4" /> : <IconEye className="w-4 h-4" />}
            </button>
          )}
        </div>
      </div>
    )
  }

  return (
    <div className="max-w-4xl mx-auto space-y-6 pb-12">
      {message && (
        <div
          className={`flex items-start gap-3 p-4 rounded-xl border ${
            message.type === 'success'
              ? 'bg-green/10 border-green/30 text-green'
              : 'bg-red/10 border-red/30 text-red'
          }`}
        >
          {message.type === 'success' ? (
            <IconCheck className="w-5 h-5 shrink-0 mt-0.5" />
          ) : (
            <IconAlertCircle className="w-5 h-5 shrink-0 mt-0.5" />
          )}
          <div>
            <p className="font-semibold text-sm">
              {message.type === 'success' ? 'Success' : 'Error'}
            </p>
            <p className="text-xs opacity-90 mt-0.5">{message.text}</p>
          </div>
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-6">
        {/* Core Auth & Service Control */}
        <div className="grid gap-6 md:grid-cols-2">
          {/* Dashboard Access */}
          <div className="bg-panel border border-border rounded-xl p-5 space-y-4 shadow-xl">
            <div className="flex items-center gap-3 border-b border-border pb-3">
              <div className="w-8 h-8 rounded-lg bg-blue/10 flex items-center justify-center text-blue">
                <IconLock className="w-5 h-5" />
              </div>
              <div>
                <h3 className="font-bold text-sm">Dashboard Security</h3>
                <p className="text-[10px] text-dim uppercase tracking-wider">Access Password</p>
              </div>
            </div>
            {renderInputField('Dashboard Password', 'DEXTER_WEB_PASSWORD', 'password', 'Enter Web UI password')}
          </div>

          {/* Service Actions */}
          <div className="bg-panel border border-border rounded-xl p-5 space-y-4 shadow-xl flex flex-col justify-between">
            <div>
              <div className="flex items-center gap-3 border-b border-border pb-3">
                <div className="w-8 h-8 rounded-lg bg-orange/10 flex items-center justify-center text-orange">
                  <IconRefresh className="w-5 h-5" />
                </div>
                <div>
                  <h3 className="font-bold text-sm">System Control</h3>
                  <p className="text-[10px] text-dim uppercase tracking-wider">Daemon Operations</p>
                </div>
              </div>
              <p className="text-xs text-dim mt-3 leading-relaxed">
                Saving settings updates the configuration on disk immediately. However, you must restart the background service for the updates to take effect in the trading engine.
              </p>
            </div>
            <button
              type="button"
              onClick={handleRestart}
              disabled={restarting}
              className="mt-4 flex items-center justify-center gap-2 w-full px-4 py-2.5 bg-orange/10 hover:bg-orange/20 text-orange rounded-lg font-semibold transition-colors disabled:opacity-50"
            >
              {restarting ? (
                <IconLoader2 className="w-4 h-4 animate-spin" />
              ) : (
                <IconRefresh className="w-4 h-4" />
              )}
              Restart Service Daemon
            </button>
          </div>
        </div>

        {/* Schwab Setup */}
        <div className="bg-panel border border-border rounded-xl p-5 space-y-4 shadow-xl">
          <div className="flex items-center gap-3 border-b border-border pb-3">
            <div className="w-8 h-8 rounded-lg bg-green/10 flex items-center justify-center text-green">
              <IconKey className="w-5 h-5" />
            </div>
            <div>
              <h3 className="font-bold text-sm">Schwab Developer Portal</h3>
              <p className="text-[10px] text-dim uppercase tracking-wider">Schwab options & Equities Auth</p>
            </div>
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            {renderInputField('App Client Key', 'SCHWAB_APP_KEY', 'password', 'Enter App Key')}
            {renderInputField('App Client Secret', 'SCHWAB_APP_SECRET', 'password', 'Enter App Secret')}
          </div>
          {renderInputField('Redirect URI', 'SCHWAB_REDIRECT_URI', 'text', 'https://127.0.0.1:8182/')}
          <div className="text-[11px] text-dim leading-relaxed bg-bg/50 p-3 rounded-lg border border-border/50">
            <strong>Onboarding Schwab:</strong> Make sure your Schwab developer app redirect URI matches the field above. After saving, run the <code>python reauth_schwab.py</code> script locally to complete the initial oauth handshakes.
          </div>
        </div>

        {/* Telegram Alerts */}
        <div className="bg-panel border border-border rounded-xl p-5 space-y-4 shadow-xl">
          <div className="flex items-center gap-3 border-b border-border pb-3">
            <div className="w-8 h-8 rounded-lg bg-blue/10 flex items-center justify-center text-blue">
              <IconBrandTelegram className="w-5 h-5" />
            </div>
            <div>
              <h3 className="font-bold text-sm">Telegram Bot alerts</h3>
              <p className="text-[10px] text-dim uppercase tracking-wider">Real-time alerts & confirmation signals</p>
            </div>
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            {renderInputField('Telegram Bot Token', 'TELEGRAM_BOT_TOKEN', 'password', '123456789:ABCdef...')}
            {renderInputField('Telegram Chat ID', 'TELEGRAM_CHAT_ID', 'text', 'e.g. -100123456789')}
          </div>
        </div>

        {/* AI Brain */}
        <div className="bg-panel border border-border rounded-xl p-5 space-y-4 shadow-xl">
          <div className="flex items-center gap-3 border-b border-border pb-3">
            <div className="w-8 h-8 rounded-lg bg-purple/10 flex items-center justify-center text-purple">
              <IconCpu className="w-5 h-5" />
            </div>
            <div>
              <h3 className="font-bold text-sm">AI Engine & LLM Configuration</h3>
              <p className="text-[10px] text-dim uppercase tracking-wider">Decision-making & analysis brain</p>
            </div>
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-1">
              <label className="block text-xs font-bold uppercase tracking-wider text-dim">LLM Provider</label>
              <select
                value={settings.LLM_PROVIDER || 'openai'}
                onChange={(e) => handleChange('LLM_PROVIDER', e.target.value)}
                className="w-full bg-bg border border-border rounded-lg px-3 py-2 text-sm text-text focus:outline-none focus:border-blue focus:ring-1 focus:ring-blue h-[38px]"
              >
                <option value="openai">OpenAI</option>
                <option value="gemini">Google Gemini</option>
                <option value="anthropic">Anthropic</option>
                <option value="kimi">Kimi Code</option>
              </select>
            </div>
            {renderInputField('LLM Model Name', 'BROWSER_USE_MODEL', 'text', 'gpt-4o or gemini-2.5-flash')}
          </div>
          <div className="grid gap-4 md:grid-cols-2 border-t border-border/40 pt-4">
            {renderInputField('OpenAI API Key', 'OPENAI_API_KEY', 'password', 'sk-...')}
            {renderInputField('Gemini API Key', 'GEMINI_API_KEY', 'password', 'AIzaSy...')}
          </div>
        </div>

        {/* Other Venues */}
        <div className="bg-panel border border-border rounded-xl p-5 space-y-4 shadow-xl">
          <div className="flex items-center gap-3 border-b border-border pb-3">
            <div className="w-8 h-8 rounded-lg bg-teal/10 flex items-center justify-center text-teal">
              <IconExchange className="w-5 h-5" />
            </div>
            <div>
              <h3 className="font-bold text-sm">Other Platform Integrations</h3>
              <p className="text-[10px] text-dim uppercase tracking-wider">OANDA, Kalshi, Topstep credentials</p>
            </div>
          </div>
          
          <div className="space-y-4">
            <h4 className="text-xs font-bold text-dim/80 border-b border-border/20 pb-1">OANDA (Forex)</h4>
            <div className="grid gap-4 md:grid-cols-2">
              {renderInputField('API Key', 'OANDA_API_KEY', 'password', 'Oanda API key')}
              {renderInputField('Account ID', 'OANDA_ACCOUNT_ID', 'text', 'Oanda account ID')}
            </div>

            <h4 className="text-xs font-bold text-dim/80 border-b border-border/20 pb-1 mt-4">Kalshi (Event Contracts)</h4>
            <div className="grid gap-4 md:grid-cols-2">
              {renderInputField('API Key (Email)', 'KALSHI_API_KEY', 'text', 'Kalshi registration email')}
              {renderInputField('API Secret', 'KALSHI_API_SECRET', 'password', 'Kalshi API token secret')}
            </div>

            <h4 className="text-xs font-bold text-dim/80 border-b border-border/20 pb-1 mt-4">Topstep (Futures Browser Automation)</h4>
            <div className="grid gap-4 md:grid-cols-2">
              {renderInputField('Username', 'TOPSTEP_USERNAME', 'text', 'Topstep username')}
              {renderInputField('Password', 'TOPSTEP_PASSWORD', 'password', 'Topstep password')}
            </div>
          </div>
        </div>

        {/* Save button */}
        <div className="flex justify-end gap-3 sticky bottom-4 bg-bg/95 backdrop-blur py-4 px-6 border border-border rounded-xl shadow-2xl z-40">
          <button
            type="submit"
            disabled={saving}
            className="flex items-center justify-center gap-2 px-6 py-3 bg-blue hover:bg-blue/90 disabled:opacity-50 text-white font-bold rounded-xl transition-colors cursor-pointer w-full md:w-auto min-w-[150px]"
          >
            {saving ? (
              <IconLoader2 className="w-5 h-5 animate-spin" />
            ) : (
              <IconCheck className="w-5 h-5" />
            )}
            Save Configuration
          </button>
        </div>
      </form>
    </div>
  )
}
