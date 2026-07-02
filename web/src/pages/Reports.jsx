import { useState } from 'react'
import ReactMarkdown from 'react-markdown'
import { IconFileText, IconX } from '@tabler/icons-react'
import { useAlphaTrader } from '../context/WebSocketContext'
import { formatTime, cn } from '../lib/utils'

function ReportViewer({ report, onClose }) {
  const [content, setContent] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useState(() => {
    let cancelled = false
    fetch(`/api/reports/${encodeURIComponent(report.name)}`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.json()
      })
      .then((data) => {
        if (!cancelled) {
          setContent(data.content || '')
          setLoading(false)
        }
      })
      .catch((e) => {
        if (!cancelled) {
          setError(e.message)
          setLoading(false)
        }
      })
    return () => {
      cancelled = true
    }
  }, [report.name])

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="bg-panel border border-border rounded-xl w-full max-w-4xl max-h-[85vh] flex flex-col shadow-2xl">
        <div className="flex items-center justify-between border-b border-border px-5 py-3">
          <div>
            <h3 className="font-semibold text-sm">{report.name}</h3>
            <div className="text-[10px] text-dim">{formatTime(report.mtime * 1000)} • {(report.size / 1024).toFixed(1)} KB</div>
          </div>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-panel-hover text-dim hover:text-text">
            <IconX className="w-5 h-5" />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-5 text-sm prose prose-invert max-w-none">
          {loading ? (
            <div className="text-dim text-center py-10">Loading report…</div>
          ) : error ? (
            <div className="text-red text-center py-10">Failed to load report: {error}</div>
          ) : (
            <ReactMarkdown>{content}</ReactMarkdown>
          )}
        </div>
      </div>
    </div>
  )
}

export default function Reports() {
  const { reports } = useAlphaTrader()
  const [selected, setSelected] = useState(null)

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">Generated Reports</h2>
        <span className="text-sm text-dim">{reports.length} reports</span>
      </div>

      {!reports || reports.length === 0 ? (
        <div className="bg-panel border border-border rounded-xl p-8 text-center text-dim text-sm">No reports yet</div>
      ) : (
        <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
          {reports.map((r) => (
            <button
              key={r.name}
              onClick={() => setSelected(r)}
              className="text-left bg-panel border border-border rounded-xl p-4 flex items-start gap-3 hover:border-blue/40 transition-colors"
            >
              <div className="w-10 h-10 rounded-lg bg-blue/10 text-blue flex items-center justify-center shrink-0">
                <IconFileText className="w-5 h-5" />
              </div>
              <div className="min-w-0">
                <div className="font-medium text-sm truncate" title={r.name}>{r.name}</div>
                <div className="text-xs text-dim mt-1">{formatTime(r.mtime * 1000)}</div>
                <div className="text-xs text-dim/70">{(r.size / 1024).toFixed(1)} KB</div>
              </div>
            </button>
          ))}
        </div>
      )}

      {selected && <ReportViewer report={selected} onClose={() => setSelected(null)} />}
    </div>
  )
}
