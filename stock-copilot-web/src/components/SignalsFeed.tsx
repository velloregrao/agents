import { RefreshCw } from 'lucide-react'

const MOCK_SIGNALS = [
  { ticker: 'TSLA', name: 'Tesla',     price: 248.52, chg: -3.9,  signal: 'WATCH',      rsi: 38, ema: 'BEARISH', momentum: 4.1, conf: 62 },
  { ticker: 'META', name: 'Meta',      price: 512.89, chg: -2.1,  signal: 'BUY SIGNAL', rsi: 44, ema: 'NEUTRAL', momentum: 6.2, conf: 74 },
  { ticker: 'NVDA', name: 'Nvidia',    price: 164.98, chg: -2.4,  signal: 'WATCH',      rsi: 41, ema: 'BEARISH', momentum: 4.5, conf: 58 },
  { ticker: 'AMZN', name: 'Amazon',    price: 200.55, chg: -0.7,  signal: 'WATCH',      rsi: 49, ema: 'NEUTRAL', momentum: 5.1, conf: 51 },
  { ticker: 'COIN', name: 'Coinbase',  price: 218.45, chg: +1.2,  signal: 'BUY SIGNAL', rsi: 58, ema: 'BULLISH', momentum: 7.3, conf: 81 },
  { ticker: 'SQ',   name: 'Block',     price:  78.92, chg: -0.4,  signal: 'WATCH',      rsi: 46, ema: 'NEUTRAL', momentum: 5.0, conf: 49 },
]

function ConfBar({ pct }: { pct: number }) {
  const color = pct >= 75 ? 'bg-green-500' : pct >= 55 ? 'bg-yellow-500' : 'bg-red-500'
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1 bg-border rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="font-mono text-xs text-muted w-8 text-right">{pct}%</span>
    </div>
  )
}

export function SignalsFeed({ onCommand }: { onCommand: (cmd: string) => void }) {
  const filters = ['All', 'Buy Signals', 'Sell Signals', 'Earnings', 'Alerts']

  return (
    <div className="flex-1 overflow-auto p-6 flex flex-col gap-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h1 className="text-xl font-medium">Signals Feed</h1>
          <span className="flex items-center gap-1.5 text-xs text-green-400">
            <span className="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse" /> Live
          </span>
        </div>
        <div className="flex items-center gap-2 text-xs text-muted">
          <RefreshCw size={12} />
          Last scan: 2 min ago
        </div>
      </div>

      {/* Filters */}
      <div className="flex gap-2">
        {filters.map((f, i) => (
          <button key={f}
            className={`px-3 py-1.5 rounded-full text-xs transition-colors cursor-pointer border-0
              ${i === 0
                ? 'bg-accent text-white'
                : 'bg-surface text-muted hover:text-white'}`}>
            {f}
          </button>
        ))}
      </div>

      {/* Signal cards grid */}
      <div className="grid grid-cols-3 gap-3">
        {MOCK_SIGNALS.map(s => {
          const isBuy = s.signal === 'BUY SIGNAL'
          const chgColor = s.chg >= 0 ? 'text-green-400' : 'text-red-400'
          return (
            <div key={s.ticker} className="card flex flex-col gap-3">
              {/* Ticker row */}
              <div className="flex items-start justify-between">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="font-mono font-medium text-white">{s.ticker}</span>
                    <span className={`text-xs px-2 py-0.5 rounded-full
                      ${isBuy ? 'bg-green-500/10 text-green-400' : 'bg-yellow-500/10 text-yellow-400'}`}>
                      {s.signal}
                    </span>
                  </div>
                  <span className="text-xs text-muted">{s.name}</span>
                </div>
                <div className="text-right">
                  <div className="font-mono text-white">${s.price.toFixed(2)}</div>
                  <div className={`font-mono text-xs ${chgColor}`}>
                    {s.chg >= 0 ? '+' : ''}{s.chg}%
                  </div>
                </div>
              </div>

              {/* Metrics */}
              <div className="grid grid-cols-3 gap-2 text-center">
                {[
                  { label: 'RSI', val: s.rsi, color: s.rsi < 40 ? 'text-red-400' : s.rsi > 60 ? 'text-green-400' : 'text-muted' },
                  { label: 'EMA', val: s.ema, color: s.ema === 'BULLISH' ? 'text-green-400' : s.ema === 'BEARISH' ? 'text-red-400' : 'text-muted' },
                  { label: 'Score', val: `${s.momentum}/10`, color: s.momentum >= 6 ? 'text-green-400' : 'text-red-400' },
                ].map(m => (
                  <div key={m.label} className="bg-bg rounded p-1.5">
                    <div className="text-xs text-muted">{m.label}</div>
                    <div className={`font-mono text-xs font-medium ${m.color}`}>{m.val}</div>
                  </div>
                ))}
              </div>

              {/* Confidence */}
              <ConfBar pct={s.conf} />

              {/* Actions */}
              <div className="flex gap-2">
                <button onClick={() => onCommand(`Analyze: ${s.ticker}`)}
                  className="flex-1 text-xs py-1.5 rounded border border-border text-muted
                             hover:border-accent hover:text-white transition-colors bg-transparent cursor-pointer">
                  Analyze
                </button>
                <button className="flex-1 text-xs py-1.5 rounded bg-accent text-white
                                   hover:bg-blue-500 transition-colors border-0 cursor-pointer">
                  Trade
                </button>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
