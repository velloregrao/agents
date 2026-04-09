import { useEffect, useState } from 'react'
import { AlertTriangle, CheckCircle, Clock } from 'lucide-react'
import { api, type Balance, type Position } from '../lib/api'

function fmt(n: number) {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(n)
}

function StatTile({ label, value, sub, subColor }: {
  label: string; value: string; sub?: string; subColor?: string
}) {
  return (
    <div className="card flex flex-col gap-1 min-w-[160px]">
      <span className="stat-label">{label}</span>
      <span className="stat-value">{value}</span>
      {sub && <span className={`text-xs font-mono ${subColor ?? 'text-muted'}`}>{sub}</span>}
    </div>
  )
}

function Sparkline({ pct }: { pct: number }) {
  const color = pct >= 0 ? '#22C55E' : '#EF4444'
  return (
    <svg width="60" height="24" viewBox="0 0 60 24">
      <polyline
        points={pct >= 0 ? '0,20 20,16 40,8 60,4' : '0,4 20,8 40,16 60,20'}
        fill="none" stroke={color} strokeWidth="1.5" strokeLinecap="round"
      />
    </svg>
  )
}

function PositionsTable({ positions }: { positions: Position[] }) {
  return (
    <div className="card flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <span className="font-medium text-sm">Open Positions ({positions.length})</span>
      </div>
      <table className="w-full text-xs">
        <thead>
          <tr className="text-muted border-b border-border">
            {['Ticker', 'Shares', 'Entry', 'Current', 'Value', 'P&L%', ''].map(h => (
              <th key={h} className="text-left py-2 pr-3 font-medium">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {positions.map(p => {
            const pct = p.unrealized_pnl_pct
            const color = pct >= 0 ? 'text-green-400' : 'text-red-400'
            return (
              <tr key={p.ticker} className="border-b border-border/50 hover:bg-white/5 transition-colors">
                <td className="py-2 pr-3 font-mono font-medium text-white">{p.ticker}</td>
                <td className="py-2 pr-3 font-mono text-muted">{p.quantity}sh</td>
                <td className="py-2 pr-3 font-mono text-muted">{fmt(p.entry_price)}</td>
                <td className="py-2 pr-3 font-mono text-white">{fmt(p.current_price)}</td>
                <td className="py-2 pr-3 font-mono text-white">{fmt(p.market_value)}</td>
                <td className={`py-2 pr-3 font-mono ${color}`}>
                  {pct >= 0 ? '+' : ''}{pct.toFixed(1)}%
                </td>
                <td className="py-2"><Sparkline pct={pct} /></td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function AlertsFeed({ onCommand }: { onCommand: (cmd: string) => void }) {
  const alerts = [
    {
      type: 'warning',
      icon: <AlertTriangle size={14} className="text-yellow-400 mt-0.5 shrink-0" />,
      bg: 'border-yellow-500/20 bg-yellow-500/5',
      text: 'AMD down 5.1% — technical analysis recommended',
      time: '2 min ago',
      action: 'Analyze AMD',
      cmd: 'Analyze: AMD',
    },
    {
      type: 'info',
      icon: <Clock size={14} className="text-blue-400 mt-0.5 shrink-0" />,
      bg: 'border-blue-500/20 bg-blue-500/5',
      text: 'Weekly reflection scheduled for 08:00 ET Monday',
      time: 'Today',
      action: null,
      cmd: '',
    },
    {
      type: 'success',
      icon: <CheckCircle size={14} className="text-green-400 mt-0.5 shrink-0" />,
      bg: 'border-green-500/20 bg-green-500/5',
      text: 'Rebalance plan executed — 5 trades filled',
      time: 'Yesterday',
      action: null,
      cmd: '',
    },
  ]

  return (
    <div className="card flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <span className="font-medium text-sm">Agent Alerts</span>
        <span className="flex items-center gap-1.5 text-xs text-green-400">
          <span className="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse" />
          Live
        </span>
      </div>
      <div className="flex flex-col gap-2">
        {alerts.map((a, i) => (
          <div key={i} className={`border rounded-lg p-3 flex flex-col gap-1.5 ${a.bg}`}>
            <div className="flex gap-2">
              {a.icon}
              <span className="text-xs text-white leading-snug">{a.text}</span>
            </div>
            <div className="flex items-center justify-between pl-5">
              <span className="text-xs text-muted">{a.time}</span>
              {a.action && (
                <button onClick={() => onCommand(a.cmd)}
                  className="text-xs text-accent hover:underline cursor-pointer bg-transparent border-0 p-0">
                  {a.action}
                </button>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

interface Props { onCommand: (cmd: string) => void }

export function Dashboard({ onCommand }: Props) {
  const [balance, setBalance] = useState<Balance | null>(null)
  const [positions, setPositions] = useState<Position[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.portfolio()
      .then(r => {
        setBalance(r.balance)
        setPositions(r.positions?.positions ?? [])
      })
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [])

  if (loading) return (
    <div className="flex-1 flex items-center justify-center text-muted text-sm">
      Loading portfolio…
    </div>
  )

  const pnlColor = (balance?.pnl_today ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'

  return (
    <div className="flex-1 overflow-auto p-6 flex flex-col gap-4">
      {/* Stat tiles */}
      <div className="flex gap-3 flex-wrap">
        <StatTile label="Portfolio Value" value={fmt(balance?.portfolio_value ?? 0)} />
        <StatTile label="Cash Available"  value={fmt(balance?.cash ?? 0)} />
        <StatTile
          label="Today's P&L"
          value={fmt(balance?.pnl_today ?? 0)}
          sub={`${(balance?.pnl_today_pct ?? 0) >= 0 ? '+' : ''}${balance?.pnl_today_pct?.toFixed(2)}%`}
          subColor={pnlColor}
        />
        <StatTile label="Buying Power" value={fmt(balance?.buying_power ?? 0)} />
      </div>

      {/* Main grid */}
      <div className="grid grid-cols-[1fr_360px] gap-4 flex-1 min-h-0">
        <PositionsTable positions={positions} />
        <AlertsFeed onCommand={onCommand} />
      </div>
    </div>
  )
}
