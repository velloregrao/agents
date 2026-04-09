import { X, CheckCircle } from 'lucide-react'
import { useState } from 'react'
import { api } from '../lib/api'

interface Trade {
  ticker: string
  side: string
  adjusted_qty: number
  trade_value: number
  current_pct: number
  target_pct: number
  risk_verdict: string
}

interface Plan {
  plan_id: string
  equity: number
  trades: Trade[]
  blocked: Trade[]
  total_sell_value: number
  total_buy_value: number
  net_cash_change: number
  rationale: string
}

function verdictBadge(v: string) {
  const map: Record<string, string> = {
    APPROVED: 'badge-approved',
    RESIZE:   'badge-resize',
    ESCALATE: 'badge-escalate',
    BLOCK:    'badge-blocked',
  }
  const icons: Record<string, string> = {
    APPROVED: '✅', RESIZE: '🔄', ESCALATE: '⚠️', BLOCK: '⛔',
  }
  return (
    <span className={map[v] ?? 'badge-blocked'}>
      {icons[v] ?? '?'} {v}
    </span>
  )
}

function fmt(n: number) {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(n)
}

interface Props {
  plan: Plan | null
  onClose: () => void
  onExecuted: () => void
}

export function TradeApprovalModal({ plan, onClose, onExecuted }: Props) {
  const [state, setState] = useState<'review' | 'executing' | 'done'>('review')
  const [result, setResult] = useState<string>('')

  if (!plan) return null
  const p = plan

  async function approve() {
    setState('executing')
    try {
      const res = await api.approveRebalance(p.plan_id) as { summary?: string }
      setResult(res?.summary ?? 'Executed.')
      setState('done')
      setTimeout(() => { onExecuted(); onClose() }, 2500)
    } catch (e) {
      setResult(`Error: ${(e as Error).message}`)
      setState('done')
    }
  }

  async function reject() {
    await api.rejectRebalance(p.plan_id).catch(() => {})
    onClose()
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />
      <div className="relative bg-surface border border-border rounded-xl w-[680px] max-h-[90vh]
                      overflow-y-auto flex flex-col shadow-2xl">

        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border shrink-0">
          <div>
            <h2 className="font-medium text-base">Portfolio Rebalancing Plan</h2>
            <p className="text-xs text-muted mt-0.5">
              Equity: {fmt(plan.equity)} &nbsp;|&nbsp;
              {plan.trades.length} trade(s) &nbsp;|&nbsp;
              Net cash: {fmt(plan.net_cash_change)}
            </p>
          </div>
          <button onClick={onClose} className="text-muted hover:text-white transition-colors bg-transparent border-0 cursor-pointer">
            <X size={18} />
          </button>
        </div>

        {state === 'review' && (
          <>
            {/* Trade table */}
            <div className="px-6 py-4">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-muted border-b border-border">
                    {['Ticker', 'Action', 'Shares', 'Value', 'Current%', 'Target%', 'Status'].map(h => (
                      <th key={h} className="text-left py-2 pr-3 font-medium">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {plan.trades.map(t => (
                    <tr key={t.ticker} className="border-b border-border/50">
                      <td className="py-2 pr-3 font-mono font-medium text-white">{t.ticker}</td>
                      <td className={`py-2 pr-3 font-medium ${t.side === 'buy' ? 'text-green-400' : 'text-red-400'}`}>
                        {t.side.toUpperCase()}
                      </td>
                      <td className="py-2 pr-3 font-mono text-muted">{t.adjusted_qty} sh</td>
                      <td className="py-2 pr-3 font-mono text-white">{fmt(t.trade_value)}</td>
                      <td className="py-2 pr-3 font-mono text-muted">{(t.current_pct * 100).toFixed(1)}%</td>
                      <td className="py-2 pr-3 font-mono text-muted">{(t.target_pct * 100).toFixed(1)}%</td>
                      <td className="py-2">{verdictBadge(t.risk_verdict)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>

              {plan.blocked.length > 0 && (
                <p className="text-xs text-muted mt-3">
                  ⛔ Blocked by risk gate: {plan.blocked.map(b => b.ticker).join(', ')}
                </p>
              )}
            </div>

            {/* Rationale */}
            <div className="mx-6 mb-4 bg-bg rounded-lg p-4 border-l-2 border-accent">
              <p className="text-xs text-muted italic leading-relaxed">"{plan.rationale}"</p>
            </div>

            {/* Buttons */}
            <div className="flex items-center justify-between px-6 py-4 border-t border-border shrink-0">
              <button onClick={reject} className="btn-danger text-sm">Reject</button>
              <button onClick={approve} className="btn-primary text-sm">
                Approve &amp; Execute ▶
              </button>
            </div>
          </>
        )}

        {state === 'executing' && (
          <div className="flex-1 flex flex-col items-center justify-center py-16 gap-4">
            <div className="w-8 h-8 border-2 border-accent border-t-transparent rounded-full animate-spin" />
            <p className="text-sm text-muted">Executing {plan.trades.length} trades…</p>
          </div>
        )}

        {state === 'done' && (
          <div className="flex-1 flex flex-col items-center justify-center py-16 gap-3">
            <CheckCircle size={40} className="text-green-400" />
            <p className="text-sm text-white font-medium">Done</p>
            <p className="text-xs text-muted">{result}</p>
          </div>
        )}
      </div>
    </div>
  )
}
