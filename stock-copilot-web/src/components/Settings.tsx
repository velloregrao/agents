import { useState } from 'react'

interface Allocation { ticker: string; target: number; current: number; color: string }

const COLORS: Record<string, string> = {
  NVDA: '#3B82F6', AAPL: '#A855F7', MSFT: '#14B8A6',
  AMZN: '#F59E0B', GOOGL: '#EC4899', AMD: '#EAB308', Cash: '#6B7280',
}

function DonutChart({ allocs }: { allocs: Allocation[] }) {
  const total = allocs.reduce((s, a) => s + a.target, 0)
  const cash  = Math.max(0, 100 - total)
  const segments = [...allocs.map(a => ({ label: a.ticker, pct: a.target, color: COLORS[a.ticker] ?? '#888' })),
                    { label: 'Cash', pct: cash, color: COLORS.Cash }]

  let cumulative = 0
  const r = 80, cx = 110, cy = 110, stroke = 28
  const circ = 2 * Math.PI * r

  return (
    <div className="flex flex-col items-center gap-4">
      <svg width="220" height="220" viewBox="0 0 220 220">
        {segments.map(s => {
          const dash  = (s.pct / 100) * circ
          const gap   = circ - dash
          const offset = circ - (cumulative / 100) * circ
          cumulative += s.pct
          return (
            <circle key={s.label} cx={cx} cy={cy} r={r}
              fill="none" stroke={s.color} strokeWidth={stroke}
              strokeDasharray={`${dash} ${gap}`}
              strokeDashoffset={offset}
              transform={`rotate(-90 ${cx} ${cy})`}
              style={{ transition: 'stroke-dasharray 0.4s ease' }}
            />
          )
        })}
        <text x={cx} y={cy - 8} textAnchor="middle" className="fill-white"
          style={{ fontFamily: 'Menlo,monospace', fontSize: 28, fontWeight: 400 }}>
          {total}%
        </text>
        <text x={cx} y={cy + 14} textAnchor="middle"
          style={{ fontFamily: 'Inter,sans-serif', fontSize: 12, fill: '#6B7280' }}>
          invested
        </text>
      </svg>

      {/* Legend */}
      <div className="flex flex-wrap gap-3 justify-center">
        {segments.map(s => (
          <div key={s.label} className="flex items-center gap-1.5 text-xs text-muted">
            <span className="w-2 h-2 rounded-full" style={{ background: s.color }} />
            {s.label} {s.pct}%
          </div>
        ))}
      </div>
    </div>
  )
}

export function Settings() {
  const [allocs, setAllocs] = useState<Allocation[]>([
    { ticker: 'NVDA',  target: 10, current: 9.6,  color: COLORS.NVDA  },
    { ticker: 'AAPL',  target: 5,  current: 5.0,  color: COLORS.AAPL  },
    { ticker: 'MSFT',  target: 5,  current: 5.1,  color: COLORS.MSFT  },
    { ticker: 'AMZN',  target: 5,  current: 5.0,  color: COLORS.AMZN  },
    { ticker: 'GOOGL', target: 5,  current: 4.9,  color: COLORS.GOOGL },
    { ticker: 'AMD',   target: 5,  current: 4.7,  color: COLORS.AMD   },
  ])
  const [saved, setSaved] = useState(false)

  function setTarget(ticker: string, val: number) {
    setAllocs(prev => prev.map(a => a.ticker === ticker ? { ...a, target: val } : a))
  }

  function handleSave() {
    setSaved(true)
    setTimeout(() => setSaved(false), 3000)
  }

  return (
    <div className="flex-1 overflow-auto p-6 flex flex-col gap-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-medium">Target Allocation</h1>
          <p className="text-xs text-muted mt-0.5">Configure target portfolio weights for the optimizer.</p>
        </div>
        <span className="text-xs text-muted">Last updated: Today</span>
      </div>

      <div className="grid grid-cols-[auto_1fr] gap-8 items-start">
        {/* Donut chart */}
        <DonutChart allocs={allocs} />

        {/* Allocation table */}
        <div className="card flex flex-col gap-0 overflow-hidden">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-muted border-b border-border bg-bg">
                {['Ticker', 'Target %', '', 'Current %', 'Drift', 'Actions'].map(h => (
                  <th key={h} className="text-left py-2.5 px-3 font-medium">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {allocs.map(a => {
                const drift = a.current - a.target
                const driftColor = Math.abs(drift) < 0.5 ? 'text-muted' : drift > 0 ? 'text-green-400' : 'text-red-400'
                return (
                  <tr key={a.ticker} className="border-b border-border/50 hover:bg-white/5 transition-colors">
                    <td className="py-2.5 px-3 font-mono font-medium text-white">{a.ticker}</td>
                    <td className="py-2.5 px-3 font-mono text-white w-12">{a.target}%</td>
                    <td className="py-2.5 px-3 w-40">
                      <input type="range" min={0} max={20} value={a.target}
                        onChange={e => setTarget(a.ticker, Number(e.target.value))}
                        className="w-full accent-accent cursor-pointer" />
                    </td>
                    <td className="py-2.5 px-3 font-mono text-muted">{a.current}%</td>
                    <td className={`py-2.5 px-3 font-mono ${driftColor}`}>
                      {drift >= 0 ? '+' : ''}{drift.toFixed(1)}%
                    </td>
                    <td className="py-2.5 px-3">
                      <button className="text-xs text-muted hover:text-red-400 transition-colors bg-transparent border-0 cursor-pointer">
                        Remove
                      </button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>

          <div className="p-3 border-t border-border">
            <button className="text-xs text-accent hover:underline bg-transparent border-0 cursor-pointer">
              + Add Ticker
            </button>
          </div>
        </div>
      </div>

      {/* Settings */}
      <div className="card flex flex-col gap-4 max-w-md">
        <h3 className="text-sm font-medium">Settings</h3>
        {[
          { label: 'Min Trade Value', value: '$50' },
          { label: 'Cash Buffer',     value: '5%'  },
        ].map(s => (
          <div key={s.label} className="flex items-center justify-between">
            <span className="text-xs text-muted">{s.label}</span>
            <input defaultValue={s.value}
              className="bg-bg border border-border rounded px-2 py-1 text-xs text-white
                         w-20 text-right outline-none focus:border-accent transition-colors" />
          </div>
        ))}
        <div className="flex items-center justify-between">
          <span className="text-xs text-muted">Reduce Untracked Positions</span>
          <div className="w-8 h-4 bg-border rounded-full relative cursor-pointer">
            <div className="w-3 h-3 bg-muted rounded-full absolute top-0.5 left-0.5 transition-transform" />
          </div>
        </div>
      </div>

      {/* Footer buttons */}
      <div className="flex items-center justify-between max-w-2xl">
        <button className="btn-ghost text-sm border border-border">Reset to Defaults</button>
        <div className="flex items-center gap-3">
          {saved && <span className="text-xs text-green-400">✓ Saved & deployed</span>}
          <button onClick={handleSave} className="btn-primary text-sm">Save &amp; Deploy</button>
        </div>
      </div>
    </div>
  )
}
