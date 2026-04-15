import { useEffect, useState, useCallback } from 'react'
import { RefreshCw } from 'lucide-react'
import { api, SignalData } from '../lib/api'

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

function SkeletonCard() {
  return (
    <div className="card flex flex-col gap-3 animate-pulse">
      <div className="flex items-start justify-between">
        <div className="flex flex-col gap-1.5">
          <div className="h-4 w-20 bg-border rounded" />
          <div className="h-3 w-28 bg-border rounded" />
        </div>
        <div className="flex flex-col items-end gap-1.5">
          <div className="h-4 w-16 bg-border rounded" />
          <div className="h-3 w-10 bg-border rounded" />
        </div>
      </div>
      <div className="grid grid-cols-3 gap-2">
        {[0, 1, 2].map(i => <div key={i} className="h-10 bg-border rounded" />)}
      </div>
      <div className="h-2 bg-border rounded-full" />
      <div className="flex gap-2">
        <div className="flex-1 h-7 bg-border rounded" />
        <div className="flex-1 h-7 bg-border rounded" />
      </div>
    </div>
  )
}

export function SignalsFeed({ onCommand }: { onCommand: (cmd: string) => void }) {
  const [signals, setSignals]     = useState<SignalData[]>([])
  const [loading, setLoading]     = useState(true)
  const [error, setError]         = useState<string | null>(null)
  const [lastScan, setLastScan]   = useState<string>('')
  const [source, setSource]       = useState<'watchlist' | 'default'>('default')
  const [activeFilter, setFilter] = useState('All')

  const filters = ['All', 'Buy Signals', 'Sell Signals', 'Watch']

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await api.signals('web-user')
      setSignals(res.signals)
      setSource(res.source)
      // Format "2 min ago" style from as_of
      const ts = new Date(res.as_of)
      const diffMs = Date.now() - ts.getTime()
      const diffMin = Math.round(diffMs / 60000)
      setLastScan(diffMin <= 1 ? 'just now' : `${diffMin} min ago`)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to load signals')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const filtered = signals.filter(s => {
    if (activeFilter === 'All')         return true
    if (activeFilter === 'Buy Signals') return s.signal === 'BUY SIGNAL'
    if (activeFilter === 'Sell Signals') return s.signal === 'SELL SIGNAL'
    if (activeFilter === 'Watch')       return s.signal === 'WATCH'
    return true
  })

  return (
    <div className="flex-1 overflow-auto p-6 flex flex-col gap-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h1 className="text-xl font-medium">Signals Feed</h1>
          {!loading && !error && (
            <span className="flex items-center gap-1.5 text-xs text-green-400">
              <span className="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse" /> Live
            </span>
          )}
          {source === 'default' && !loading && (
            <span className="text-xs text-muted">(default tickers — add to watchlist to customise)</span>
          )}
        </div>
        <div className="flex items-center gap-2 text-xs text-muted">
          <button
            onClick={load}
            disabled={loading}
            className="flex items-center gap-1 hover:text-white transition-colors disabled:opacity-40 bg-transparent border-0 cursor-pointer p-0"
            title="Refresh signals"
          >
            <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
          </button>
          {lastScan && <span>Last scan: {lastScan}</span>}
        </div>
      </div>

      {/* Filters */}
      <div className="flex gap-2">
        {filters.map(f => (
          <button key={f}
            onClick={() => setFilter(f)}
            className={`px-3 py-1.5 rounded-full text-xs transition-colors cursor-pointer border-0
              ${f === activeFilter
                ? 'bg-accent text-white'
                : 'bg-surface text-muted hover:text-white'}`}>
            {f}
          </button>
        ))}
      </div>

      {/* Error state */}
      {error && (
        <div className="card text-red-400 text-sm">
          ⚠️ {error}{' '}
          <button onClick={load} className="underline bg-transparent border-0 cursor-pointer text-red-400">Retry</button>
        </div>
      )}

      {/* Signal cards grid */}
      <div className="grid grid-cols-3 gap-3">
        {loading
          ? Array.from({ length: 6 }).map((_, i) => <SkeletonCard key={i} />)
          : filtered.length === 0
            ? (
              <div className="col-span-3 text-center text-muted text-sm py-12">
                No {activeFilter === 'All' ? '' : activeFilter.toLowerCase() + ' '}signals found.
              </div>
            )
            : filtered.map(s => {
              const isBuy  = s.signal === 'BUY SIGNAL'
              const isSell = s.signal === 'SELL SIGNAL'
              const signalClass = isBuy
                ? 'bg-green-500/10 text-green-400'
                : isSell
                  ? 'bg-red-500/10 text-red-400'
                  : 'bg-yellow-500/10 text-yellow-400'
              const chgColor = s.change_pct >= 0 ? 'text-green-400' : 'text-red-400'

              return (
                <div key={s.ticker} className="card flex flex-col gap-3">
                  {/* Ticker row */}
                  <div className="flex items-start justify-between">
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="font-mono font-medium text-white">{s.ticker}</span>
                        <span className={`text-xs px-2 py-0.5 rounded-full ${signalClass}`}>
                          {s.signal}
                        </span>
                      </div>
                      <span className="text-xs text-muted">{s.name}</span>
                    </div>
                    <div className="text-right">
                      <div className="font-mono text-white">${s.price.toFixed(2)}</div>
                      <div className={`font-mono text-xs ${chgColor}`}>
                        {s.change_pct >= 0 ? '+' : ''}{s.change_pct.toFixed(1)}%
                      </div>
                    </div>
                  </div>

                  {/* Metrics */}
                  <div className="grid grid-cols-3 gap-2 text-center">
                    {[
                      {
                        label: 'RSI',
                        val: s.rsi.toFixed(0),
                        color: s.rsi < 35 ? 'text-green-400' : s.rsi > 65 ? 'text-red-400' : 'text-muted',
                      },
                      {
                        label: 'EMA',
                        val: s.ema_signal,
                        color: s.ema_signal === 'BULLISH' ? 'text-green-400' : s.ema_signal === 'BEARISH' ? 'text-red-400' : 'text-muted',
                      },
                      {
                        label: 'Score',
                        val: `${s.momentum_score}/10`,
                        color: s.momentum_score >= 6 ? 'text-green-400' : s.momentum_score <= 4 ? 'text-red-400' : 'text-muted',
                      },
                    ].map(m => (
                      <div key={m.label} className="bg-bg rounded p-1.5">
                        <div className="text-xs text-muted">{m.label}</div>
                        <div className={`font-mono text-xs font-medium ${m.color}`}>{m.val}</div>
                      </div>
                    ))}
                  </div>

                  {/* Confidence bar */}
                  <ConfBar pct={s.confidence} />

                  {/* Actions */}
                  <div className="flex gap-2">
                    <button onClick={() => onCommand(`Analyze: ${s.ticker}`)}
                      className="flex-1 text-xs py-1.5 rounded border border-border text-muted
                                 hover:border-accent hover:text-white transition-colors bg-transparent cursor-pointer">
                      Analyze
                    </button>
                    <button onClick={() => onCommand(`buy ${s.ticker}`)}
                      className="flex-1 text-xs py-1.5 rounded bg-accent text-white
                                 hover:bg-blue-500 transition-colors border-0 cursor-pointer">
                      Trade
                    </button>
                  </div>
                </div>
              )
            })
        }
      </div>
    </div>
  )
}
