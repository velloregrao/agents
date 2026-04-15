import { useEffect, useState, useCallback } from 'react'
import { RefreshCw, Rocket, AlertTriangle, Eye, ClipboardList, PauseCircle } from 'lucide-react'
import { api, type IpoWatchProfileStatus, type IpoWatchBreakdown } from '../lib/api'

// ── Signal config ─────────────────────────────────────────────────────────────

type Signal = 'ACT' | 'PREPARE' | 'WATCH' | 'RISK' | 'HOLD' | 'INACTIVE'

const SIGNAL_META: Record<Signal, { label: string; color: string; bg: string; Icon: React.ElementType }> = {
  ACT:      { label: 'ACT',     color: 'text-green-400',  bg: 'bg-green-500/10 border-green-500/30',  Icon: Rocket       },
  PREPARE:  { label: 'PREPARE', color: 'text-blue-400',   bg: 'bg-blue-500/10  border-blue-500/30',   Icon: ClipboardList },
  WATCH:    { label: 'WATCH',   color: 'text-yellow-400', bg: 'bg-yellow-500/10 border-yellow-500/30', Icon: Eye           },
  RISK:     { label: 'RISK',    color: 'text-red-400',    bg: 'bg-red-500/10   border-red-500/30',    Icon: AlertTriangle },
  HOLD:     { label: 'HOLD',    color: 'text-muted',      bg: 'bg-surface      border-border',        Icon: PauseCircle   },
  INACTIVE: { label: '—',       color: 'text-muted',      bg: 'bg-surface      border-border',        Icon: PauseCircle   },
}

const SIGNAL_DESC: Record<Signal, string> = {
  ACT:      'IPO appears imminent — consider proxy position.',
  PREPARE:  'Strong signals — build watchlist and sizing plan.',
  WATCH:    'Early indicators — begin monitoring proxies.',
  RISK:     'Thesis weakened — reassess proxy exposure.',
  HOLD:     'No new developments — maintain current stance.',
  INACTIVE: 'No data yet — run a scan to populate.',
}

// ── Valuation formatter ───────────────────────────────────────────────────────

function fmtVal(usd: number | undefined): string {
  if (!usd) return '—'
  if (usd >= 1e12) return `$${(usd / 1e12).toFixed(2)}T`
  if (usd >= 1e9)  return `$${Math.round(usd / 1e9)}B`
  return `$${usd}`
}

// ── Score bar ─────────────────────────────────────────────────────────────────

function ScoreBar({ score }: { score: number }) {
  const color = score >= 75 ? 'bg-green-500' : score >= 55 ? 'bg-blue-500' : score >= 30 ? 'bg-yellow-500' : 'bg-red-500'
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 bg-border rounded-full overflow-hidden">
        <div className={`h-full rounded-full transition-all ${color}`} style={{ width: `${score}%` }} />
      </div>
      <span className="font-mono text-xs text-muted w-12 text-right">{score.toFixed(1)}/100</span>
    </div>
  )
}

// ── Breakdown pill row ────────────────────────────────────────────────────────

function BreakdownPills({ bd }: { bd: IpoWatchBreakdown }) {
  const pills = [
    { label: 'S-1',      active: bd.s1_detected,       activeClass: 'text-green-400 border-green-500/40 bg-green-500/10' },
    { label: 'Roadshow', active: bd.roadshow_detected,  activeClass: 'text-green-400 border-green-500/40 bg-green-500/10' },
    { label: `Sentiment: ${bd.sentiment_label}`,
      active: bd.sentiment_label === 'positive',
      activeClass: bd.sentiment_label === 'negative'
        ? 'text-red-400 border-red-500/40 bg-red-500/10'
        : 'text-blue-400 border-blue-500/40 bg-blue-500/10',
    },
  ]
  return (
    <div className="flex flex-wrap gap-1.5">
      {pills.map(p => (
        <span
          key={p.label}
          className={`text-[10px] px-2 py-0.5 rounded-full border font-medium
            ${p.active ? p.activeClass : 'text-muted border-border bg-transparent'}`}
        >
          {p.active && p.label.startsWith('S-1') ? '✓ ' : ''}
          {p.active && p.label.startsWith('Roadshow') ? '✓ ' : ''}
          {p.label}
        </span>
      ))}
    </div>
  )
}

// ── Proxy changes table ───────────────────────────────────────────────────────

function ProxyRow({ ticker, pct }: { ticker: string; pct: number | null }) {
  const sign  = pct === null ? null : pct >= 0 ? '+' : ''
  const color = pct === null ? 'text-muted' : pct >= 0 ? 'text-green-400' : 'text-red-400'
  return (
    <div className="flex justify-between items-center text-xs">
      <span className="font-mono text-muted">{ticker}</span>
      <span className={`font-mono ${color}`}>
        {pct === null ? '—' : `${sign}${pct.toFixed(2)}%`}
      </span>
    </div>
  )
}

// ── Profile card ──────────────────────────────────────────────────────────────

interface ProfileCardProps {
  profile: IpoWatchProfileStatus
  valuation?: number
  onAnalyze: (ticker: string) => void
}

function ProfileCard({ profile, valuation, onAnalyze }: ProfileCardProps) {
  const signal = (profile.last_signal ?? 'INACTIVE') as Signal
  const meta   = SIGNAL_META[signal] ?? SIGNAL_META.INACTIVE
  const { Icon } = meta
  const hasData = profile.last_score !== null && profile.breakdown !== null

  return (
    <div className={`card flex flex-col gap-3 border ${meta.bg}`}>
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <div className="flex items-center gap-2 mb-0.5">
            <span className="font-mono font-semibold text-white text-sm">{profile.ticker}</span>
            <span className={`flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-full border font-semibold ${meta.bg} ${meta.color}`}>
              <Icon size={10} />
              {meta.label}
            </span>
          </div>
          <span className="text-xs text-muted">{profile.company_name}</span>
        </div>
        <div className="text-right text-xs text-muted">
          <div>{profile.estimated_listing_window}</div>
          {valuation && <div className="font-mono">{fmtVal(valuation)}</div>}
        </div>
      </div>

      {/* Signal description */}
      <p className="text-xs text-muted leading-relaxed">{SIGNAL_DESC[signal]}</p>

      {/* Score bar */}
      {hasData ? (
        <>
          <ScoreBar score={profile.last_score!} />
          <BreakdownPills bd={profile.breakdown!} />
        </>
      ) : (
        <div className="text-xs text-muted italic">Run a scan to see score.</div>
      )}

      {/* Proxy momentum breakdown */}
      {hasData && profile.breakdown!.proxy_changes && Object.keys(profile.breakdown!.proxy_changes).length > 0 && (
        <div className="border-t border-border pt-2 flex flex-col gap-1">
          <span className="text-[10px] text-muted uppercase tracking-wide">Proxy 1-week</span>
          {Object.entries(profile.breakdown!.proxy_changes).map(([t, pct]) => (
            <ProxyRow key={t} ticker={t} pct={pct} />
          ))}
        </div>
      )}

      {/* Proxy stocks list (when no data yet) */}
      {!hasData && profile.proxy_stocks.length > 0 && (
        <div className="text-xs text-muted">
          Proxies: <span className="font-mono">{profile.proxy_stocks.join(', ')}</span>
        </div>
      )}

      {/* Footer */}
      <div className="flex items-center justify-between pt-1 border-t border-border">
        <span className="text-[10px] text-muted">
          {profile.last_checked
            ? `Checked ${profile.last_checked.slice(0, 16).replace('T', ' ')} UTC`
            : 'Not yet scanned'}
        </span>
        <button
          onClick={() => onAnalyze(profile.proxy_stocks[0] ?? profile.ticker)}
          className="text-[10px] px-2.5 py-1 rounded border border-border text-muted
                     hover:border-accent hover:text-white transition-colors bg-transparent cursor-pointer"
        >
          Analyze proxy
        </button>
      </div>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

interface Props {
  onCommand: (cmd: string) => void
}

export function IpoWatch({ onCommand }: Props) {
  const [profiles,    setProfiles]    = useState<IpoWatchProfileStatus[]>([])
  const [loading,     setLoading]     = useState(true)
  const [scanning,    setScanning]    = useState(false)
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null)
  const [runResult,   setRunResult]   = useState<string | null>(null)
  // Valuations come from /ipo-watch/profiles (includes estimated_valuation_usd)
  const [valuations,  setValuations]  = useState<Record<string, number>>({})

  const loadStatus = useCallback(async () => {
    setLoading(true)
    try {
      const [statusRes, profilesRes] = await Promise.all([
        api.ipoWatchStatus(),
        api.ipoWatchProfiles(),
      ])
      setProfiles(statusRes.profiles)
      const vals: Record<string, number> = {}
      profilesRes.profiles.forEach(p => { vals[p.ticker] = p.estimated_valuation_usd })
      setValuations(vals)
      setLastRefresh(new Date())
    } catch (err) {
      console.error('[IpoWatch] load failed:', err)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { loadStatus() }, [loadStatus])

  async function handleRunScan() {
    setScanning(true)
    setRunResult(null)
    try {
      const result = await api.ipoWatchRun()
      setRunResult(
        `Scan complete — ${result.profiles_checked} profile(s) checked, ` +
        `${result.alerts_dispatched.filter(d => d.dispatched.length > 1).length} new alert(s) dispatched.`
      )
      // Reload status from DB after scan completes
      await loadStatus()
    } catch (err) {
      setRunResult(`Scan failed: ${err instanceof Error ? err.message : String(err)}`)
    } finally {
      setScanning(false)
    }
  }

  return (
    <div className="flex-1 overflow-auto p-6 flex flex-col gap-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h1 className="text-xl font-medium">IPO Watch</h1>
          <span className="text-xs text-muted bg-surface border border-border px-2 py-0.5 rounded-full">
            {profiles.length} tracked
          </span>
        </div>
        <div className="flex items-center gap-3">
          {lastRefresh && (
            <span className="text-xs text-muted">
              Updated {lastRefresh.toLocaleTimeString()}
            </span>
          )}
          <button
            onClick={handleRunScan}
            disabled={scanning}
            className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded border border-border
                       text-muted hover:border-accent hover:text-white transition-colors
                       bg-transparent cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <RefreshCw size={12} className={scanning ? 'animate-spin' : ''} />
            {scanning ? 'Scanning…' : 'Run Scan'}
          </button>
        </div>
      </div>

      {/* Scan result banner */}
      {runResult && (
        <div className="text-xs px-4 py-2.5 rounded border border-blue-500/30 bg-blue-500/10 text-blue-300">
          {runResult}
        </div>
      )}

      {/* Legend */}
      <div className="flex flex-wrap gap-3">
        {(['ACT', 'PREPARE', 'WATCH', 'RISK', 'HOLD'] as Signal[]).map(s => {
          const m = SIGNAL_META[s]
          const { Icon } = m
          return (
            <div key={s} className="flex items-center gap-1.5 text-xs">
              <Icon size={11} className={m.color} />
              <span className={m.color}>{m.label}</span>
              <span className="text-muted">—</span>
              <span className="text-muted">{SIGNAL_DESC[s]}</span>
            </div>
          )
        })}
      </div>

      {/* Cards */}
      {loading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {[0, 1, 2].map(i => (
            <div key={i} className="card animate-pulse h-52 bg-surface" />
          ))}
        </div>
      ) : profiles.length === 0 ? (
        <div className="flex flex-col items-center justify-center h-48 gap-3 text-muted">
          <Rocket size={32} className="opacity-30" />
          <p className="text-sm">No active IPO profiles found.</p>
          <button onClick={handleRunScan} className="text-xs underline hover:text-white cursor-pointer">
            Run a scan
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {profiles.map(p => (
            <ProfileCard
              key={p.ticker}
              profile={p}
              valuation={valuations[p.ticker]}
              onAnalyze={ticker => onCommand(`Analyze: ${ticker}`)}
            />
          ))}
        </div>
      )}

      {/* Threshold reference */}
      <div className="mt-2 pt-4 border-t border-border">
        <p className="text-xs text-muted mb-2 font-medium">Score thresholds</p>
        <div className="grid grid-cols-4 gap-2">
          {[
            { label: 'ACT ≥ 75',     color: 'text-green-400',  bar: 'bg-green-500'  },
            { label: 'PREPARE ≥ 55', color: 'text-blue-400',   bar: 'bg-blue-500'   },
            { label: 'WATCH ≥ 30',   color: 'text-yellow-400', bar: 'bg-yellow-500' },
            { label: 'RISK < 20',    color: 'text-red-400',    bar: 'bg-red-500'    },
          ].map(t => (
            <div key={t.label} className="flex items-center gap-2">
              <div className={`w-2 h-2 rounded-full ${t.bar} shrink-0`} />
              <span className={`text-xs ${t.color}`}>{t.label}</span>
            </div>
          ))}
        </div>
        <p className="text-[10px] text-muted mt-2">
          Composite score = proxy momentum (0–20) + news sentiment (0–10) + S-1 detected (40) + roadshow (30).
          Scans run every 4 hours via APScheduler.
        </p>
      </div>
    </div>
  )
}
