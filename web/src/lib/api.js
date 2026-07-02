const API_BASE = ''

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
}

