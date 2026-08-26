import { useEffect, useState } from 'react'
import { IconShieldCheck, IconShieldX, IconRefresh } from '@tabler/icons-react'
import { api } from '../lib/api'

export default function Audit() {
  const [records, setRecords] = useState([])
  const [integrity, setIntegrity] = useState(null)
  const [type, setType] = useState('')
  const [limit, setLimit] = useState(50)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const load = async () => {
    setLoading(true)
    setError('')
    try {
      const params = { limit }
      if (type) params.type = type
      const data = await api.audit(params)
      setRecords(data.records || [])
      setIntegrity(data.integrity)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  return (
    <div className="space-y-5">
      <div className="bg-panel border border-border rounded-xl p-5">
        <div className="flex flex-wrap items-end gap-3 mb-4">
          <div>
            <label className="block text-xs text-dim mb-1.5 uppercase tracking-wide">Type</label>
            <input
              value={type}
              onChange={(e) => setType(e.target.value)}
              placeholder="e.g. trade_intent"
              className="bg-bg border border-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-blue w-40"
            />
          </div>
          <div>
            <label className="block text-xs text-dim mb-1.5 uppercase tracking-wide">Limit</label>
            <input
              type="number"
              value={limit}
              onChange={(e) => setLimit(Number(e.target.value))}
              className="bg-bg border border-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-blue w-24"
            />
          </div>
          <button
            onClick={load}
            disabled={loading}
            className="bg-blue hover:bg-blue/90 disabled:opacity-50 text-white text-sm font-semibold px-4 py-2 rounded-lg flex items-center gap-2"
          >
            {loading ? 'Loading...' : <><IconRefresh className="w-4 h-4" /> Query</>}
          </button>
        </div>

        {integrity && (
          <div className={`flex items-center gap-2 text-sm ${integrity.valid ? 'text-green' : 'text-red'}`}>
            {integrity.valid ? <IconShieldCheck className="w-5 h-5" /> : <IconShieldX className="w-5 h-5" />}
            <span>
              Integrity: {integrity.valid ? 'Valid' : 'Compromised'} · Checked {integrity.records_checked} records
            </span>
          </div>
        )}
        {error && <div className="mt-3 text-red text-sm">{error}</div>}
      </div>

      <div className="bg-panel border border-border rounded-xl overflow-hidden">
        <div className="px-5 py-3 border-b border-border text-xs font-bold uppercase tracking-wide text-dim">Audit Records</div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-bg text-dim text-xs uppercase tracking-wide">
              <tr>
                <th className="text-left px-4 py-2">Seq</th>
                <th className="text-left px-4 py-2">Type</th>
                <th className="text-left px-4 py-2">Timestamp</th>
                <th className="text-left px-4 py-2">Hash</th>
                <th className="text-left px-4 py-2">Payload</th>
              </tr>
            </thead>
            <tbody>
              {records.map((r) => (
                <tr key={r.seq} className="border-t border-border hover:bg-bg/50">
                  <td className="px-4 py-2 font-mono">{r.seq}</td>
                  <td className="px-4 py-2">{r.type}</td>
                  <td className="px-4 py-2 text-dim">{new Date(r.timestamp).toLocaleString()}</td>
                  <td className="px-4 py-2 font-mono text-xs text-dim">{r.hash.slice(0, 16)}…</td>
                  <td className="px-4 py-2">
                    <pre className="text-xs text-dim max-w-xs truncate">{JSON.stringify(r.payload)}</pre>
                  </td>
                </tr>
              ))}
              {records.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-4 py-6 text-dim text-center">No audit records found.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
