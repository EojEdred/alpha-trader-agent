const API_BASE = import.meta.env.VITE_API_BASE_URL || ''

async function request(path, options = {}) {
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(options.headers || {}),
    },
    credentials: 'same-origin',
  })
  if (res.status === 401) {
    const err = new Error('Unauthorized')
    err.status = 401
    throw err
  }
  if (!res.ok) {
    const text = await res.text()
    throw new Error(text || `HTTP ${res.status}`)
  }
  if (res.status === 204) return null
  return res.json()
}

export const api = {
  me: () => request('/api/me'),
  login: (password) => request('/api/login', { method: 'POST', body: JSON.stringify({ password }) }),
  logout: () => request('/api/logout', { method: 'POST', body: '{}' }),
  status: () => request('/api/status'),
  trades: () => request('/api/trades'),
  agents: () => request('/api/agents'),
  risk: () => request('/api/risk'),
  positions: () => request('/api/positions'),
  pending: () => request('/api/pending'),
  pnl: () => request('/api/pnl'),
  reports: () => request('/api/reports'),
  workflows: () => request('/api/workflows'),
  control: (action) => request(`/api/control/${action}`, { method: 'POST', body: '{}' }),
  trade: (body) => request('/api/trades', { method: 'POST', body: JSON.stringify(body) }),
  approve: (id) => request(`/api/approve/${id}`, { method: 'POST', body: '{}' }),
  reject: (id) => request(`/api/reject/${id}`, { method: 'POST', body: '{}' }),
  runWorkflow: (id) => request(`/api/workflows/${id}/run`, { method: 'POST', body: '{}' }),
  chat: (message) => request('/api/chat', { method: 'POST', body: JSON.stringify({ message }) }),
  serviceRestart: () => request('/api/service/restart', { method: 'POST', body: '{}' }),
  serviceStatus: () => request('/api/service/status'),
  getSettings: () => request('/api/settings'),
  saveSettings: (settings) => request('/api/settings', { method: 'POST', body: JSON.stringify({ settings }) }),

  // Research / analysts / market data / strategies / audit
  researchAgendas: () => request('/api/research/agendas'),
  researchAgenda: (name) => request(`/api/research/agendas/${encodeURIComponent(name)}`),
  runResearch: (symbols) => request('/api/research/run', { method: 'POST', body: JSON.stringify({ symbols }) }),
  analysts: () => request('/api/analysts'),
  runAnalyst: (name, symbol) => request(`/api/analysts/${encodeURIComponent(name)}/analyze`, { method: 'POST', body: JSON.stringify({ symbol }) }),
  marketDataMassive: (symbol) => request(`/api/market-data/${encodeURIComponent(symbol)}/massive`),
  runAutoHedge: (task) => request('/api/autohedge/run', { method: 'POST', body: JSON.stringify({ task }) }),
  runValueCell: (symbol) => request('/api/valuecell/analyze', { method: 'POST', body: JSON.stringify({ symbol }) }),
  audit: (params = {}) => request(`/api/audit?${new URLSearchParams(params).toString()}`),

  // Signal feed / copy-trade
  signals: (params = {}) => request(`/api/signals?${new URLSearchParams(params).toString()}`),
  copySignal: (id, body) => request(`/api/signals/${encodeURIComponent(id)}/copy`, { method: 'POST', body: JSON.stringify(body) }),

  // Apex / Tradovate
  tradovateAccount: () => request('/api/tradovate/account'),
  tradovatePositions: () => request('/api/tradovate/positions'),
  tradovateOrders: () => request('/api/tradovate/orders'),
  tradovatePlaceOrder: (body) => request('/api/tradovate/order', { method: 'POST', body: JSON.stringify(body) }),
}

