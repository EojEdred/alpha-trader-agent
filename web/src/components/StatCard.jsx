export default function StatCard({ label, value, subtext, icon: Icon, color = 'blue' }) {
  const colorClasses = {
    blue: 'bg-blue/10 text-blue',
    green: 'bg-green/10 text-green',
    yellow: 'bg-yellow/10 text-yellow',
    red: 'bg-red/10 text-red',
    dim: 'bg-dim/10 text-dim',
  }

  return (
    <div className="bg-panel border border-border rounded-xl p-4 flex items-start justify-between">
      <div>
        <div className="text-xs font-medium text-dim uppercase tracking-wide mb-1">{label}</div>
        <div className="text-2xl font-bold">{value}</div>
        {subtext && <div className="text-xs text-dim mt-1">{subtext}</div>}
      </div>
      {Icon && (
        <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${colorClasses[color]}`}>
          <Icon className="w-5 h-5" />
        </div>
      )}
    </div>
  )
}
