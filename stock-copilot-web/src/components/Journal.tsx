import { FileText } from 'lucide-react'

export function Journal({ onViewPositions }: { onViewPositions: () => void }) {
  return (
    <div className="flex-1 overflow-auto p-6 flex flex-col gap-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-medium">Trade Journal &amp; Digest</h1>
        <div className="flex items-center gap-2 px-3 py-1.5 border border-border rounded-lg text-xs text-muted cursor-pointer hover:border-accent transition-colors">
          📅 Last 30 Days ▾
        </div>
      </div>

      {/* Summary tiles */}
      <div className="grid grid-cols-3 gap-3">
        {[
          { label: 'Total Trades', value: '0' },
          { label: 'Win Rate',     value: '—' },
          { label: 'Total P&L',   value: '—' },
        ].map(t => (
          <div key={t.label} className="card flex flex-col gap-1">
            <span className="stat-label">{t.label}</span>
            <span className="font-mono text-3xl text-white">{t.value}</span>
          </div>
        ))}
      </div>

      {/* Warning banner */}
      <div className="border border-yellow-500/30 bg-yellow-500/5 rounded-lg px-4 py-3">
        <span className="text-yellow-400 text-sm">
          Not enough data — need 3+ closed trades
        </span>
      </div>

      {/* Weekly reflection */}
      <div className="card flex flex-col gap-3 flex-1">
        <div className="flex items-center justify-between">
          <h2 className="font-medium text-sm">Weekly Reflection — Mon Mar 30</h2>
          <span className="text-xs px-2 py-1 bg-accent/10 text-accent rounded-full">
            Next digest: Monday 08:00 ET
          </span>
        </div>

        <div className="flex-1 bg-bg rounded-lg flex flex-col items-center justify-center gap-3 py-12">
          <FileText size={36} className="text-muted" />
          <p className="text-sm text-muted text-center">
            Digest not yet available — no closed trades this week.
          </p>
        </div>

        <button
          onClick={onViewPositions}
          className="btn-primary text-sm self-center px-6">
          View Open Positions →
        </button>
      </div>
    </div>
  )
}
