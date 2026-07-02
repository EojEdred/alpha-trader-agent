import { IconFileText } from '@tabler/icons-react'
import { formatTime } from '../lib/utils'

export default function ReportList({ reports }) {
  if (!reports || reports.length === 0) {
    return (
      <div className="bg-panel border border-border rounded-xl p-8 text-center text-dim text-sm">
        No reports yet
      </div>
    )
  }

  return (
    <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
      {reports.map((r) => (
        <div
          key={r.name}
          className="bg-panel border border-border rounded-xl p-4 flex items-start gap-3 hover:border-border/80 transition-colors"
        >
          <div className="w-10 h-10 rounded-lg bg-blue/10 text-blue flex items-center justify-center shrink-0">
            <IconFileText className="w-5 h-5" />
          </div>
          <div className="min-w-0">
            <div className="font-medium text-sm truncate" title={r.name}>{r.name}</div>
            <div className="text-xs text-dim mt-1">{formatTime(r.mtime * 1000)}</div>
            <div className="text-xs text-dim/70">{(r.size / 1024).toFixed(1)} KB</div>
          </div>
        </div>
      ))}
    </div>
  )
}
