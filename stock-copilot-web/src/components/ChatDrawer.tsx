import { useEffect, useRef, useState } from 'react'
import { X, Send, ShieldCheck, ShieldAlert, CheckCircle, XCircle } from 'lucide-react'
import { api } from '../lib/api'

interface Message {
  role: 'user' | 'agent'
  text: string
  loading?: boolean
  requiresApproval?: boolean
  approvalContext?: Record<string, unknown>
  approvalResolved?: 'approved' | 'rejected'
}

function ApprovalCard({
  approvalContext,
  onResolved,
}: {
  approvalContext: Record<string, unknown>
  onResolved: (decision: 'approved' | 'rejected', resultText: string) => void
}) {
  const [busy, setBusy] = useState(false)
  const isRebalance = approvalContext.alert_type === 'rebalance'

  // Rebalance plan fields
  const plan_id = approvalContext.plan_id as string
  const trades  = (approvalContext.trades as Array<Record<string, unknown>>) ?? []

  // Single-trade escalation fields
  const approval_id = approvalContext.approval_id as string
  const ticker      = approvalContext.ticker as string
  const side        = approvalContext.side as string
  const qty         = approvalContext.qty as number

  async function decide(decision: 'approve' | 'reject') {
    setBusy(true)
    try {
      let resultText: string
      if (isRebalance) {
        if (decision === 'approve') {
          const res = await api.approveRebalance(plan_id) as { summary?: string }
          resultText = res?.summary ?? `Rebalance executed — ${trades.length} trade(s).`
        } else {
          await api.rejectRebalance(plan_id)
          resultText = 'Rebalance plan rejected.'
        }
      } else {
        const res = await api.approveDecision(approval_id, decision)
        resultText = res.text ?? res.response ?? (decision === 'approve' ? 'Trade executed.' : 'Trade rejected.')
      }
      onResolved(decision === 'approve' ? 'approved' : 'rejected', resultText)
    } catch (e) {
      onResolved('rejected', `Error: ${(e as Error).message}`)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="mt-2 border border-yellow-500/40 bg-yellow-500/5 rounded-lg p-3 flex flex-col gap-3">
      <div className="text-xs text-yellow-400 font-medium">⚠️ Human Approval Required</div>
      <div className="text-xs text-muted">
        {isRebalance
          ? <><span className="text-white font-mono">{trades.length} trade(s)</span> — rebalance plan</>
          : <><span className="text-white font-mono">{side?.toUpperCase()} {qty} {ticker}</span> — confirm to execute on paper account</>
        }
      </div>
      <div className="flex gap-2">
        <button
          onClick={() => decide('approve')}
          disabled={busy}
          className="flex-1 flex items-center justify-center gap-1.5 text-xs py-1.5 rounded
                     bg-green-500/10 text-green-400 border border-green-500/30
                     hover:bg-green-500/20 transition-colors disabled:opacity-40 cursor-pointer"
        >
          <CheckCircle size={12} /> Approve
        </button>
        <button
          onClick={() => decide('reject')}
          disabled={busy}
          className="flex-1 flex items-center justify-center gap-1.5 text-xs py-1.5 rounded
                     bg-red-500/10 text-red-400 border border-red-500/30
                     hover:bg-red-500/20 transition-colors disabled:opacity-40 cursor-pointer"
        >
          <XCircle size={12} /> Reject
        </button>
      </div>
    </div>
  )
}

function RiskStatus() {
  const rules = [
    { label: 'Circuit Breaker',      status: 'SAFE',    ok: true  },
    { label: 'Position Limit',       status: 'WITHIN',  ok: true  },
    { label: 'Sector Concentration', status: 'WARNING', ok: false },
    { label: 'Correlation Guard',    status: 'SAFE',    ok: true  },
  ]
  return (
    <div className="card flex flex-col gap-2 mt-3">
      <span className="text-xs text-muted font-medium">Risk Status</span>
      {rules.map(r => (
        <div key={r.label} className="flex items-center justify-between text-xs">
          <span className="text-muted">{r.label}</span>
          <span className={r.ok ? 'text-green-400' : 'text-yellow-400'}>
            {r.ok
              ? <ShieldCheck size={12} className="inline mr-1" />
              : <ShieldAlert size={12} className="inline mr-1" />}
            {r.status}
          </span>
        </div>
      ))}
    </div>
  )
}

interface Props {
  open: boolean
  onClose: () => void
  initialCmd: string
  balance: { equity: number; cash: number } | null
  activeTicker: string
}

export function ChatDrawer({ open, onClose, initialCmd, balance, activeTicker }: Props) {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput]       = useState('')
  const [sending, setSending]   = useState(false)
  const bottomRef               = useRef<HTMLDivElement>(null)

  // Pre-fill input when triggered from ActionBar
  useEffect(() => {
    if (open && initialCmd) setInput(initialCmd)
  }, [open, initialCmd])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  async function send(text: string) {
    if (!text.trim()) return
    setInput('')
    setSending(true)

    setMessages(m => [...m,
      { role: 'user', text },
      { role: 'agent', text: '', loading: true },
    ])

    try {
      const res = await api.sendMessage(text)
      setMessages(m => {
        const copy = [...m]
        copy[copy.length - 1] = {
          role: 'agent',
          text: res.text ?? res.response ?? '(no response)',
          requiresApproval: res.requires_approval,
          approvalContext:  res.approval_context as Record<string, unknown>,
        }
        return copy
      })
    } catch (e) {
      setMessages(m => {
        const copy = [...m]
        copy[copy.length - 1] = { role: 'agent', text: `Error: ${(e as Error).message}` }
        return copy
      })
    } finally {
      setSending(false)
    }
  }

  const chips = ['Portfolio', 'Analyze: AMD', 'News: NVDA', 'Optimize', 'Digest']

  return (
    <>
      {/* Backdrop */}
      {open && (
        <div className="fixed inset-0 bg-black/40 z-30" onClick={onClose} />
      )}

      {/* Drawer */}
      <div className={`fixed top-0 right-0 h-full w-[480px] bg-bg border-l border-border z-40
                       flex flex-col transition-transform duration-300
                       ${open ? 'translate-x-0' : 'translate-x-full'}`}>

        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-border shrink-0">
          <span className="font-medium text-sm">Stock Copilot Chat</span>
          <button onClick={onClose} className="text-muted hover:text-white transition-colors bg-transparent border-0 cursor-pointer">
            <X size={18} />
          </button>
        </div>

        <div className="flex flex-1 min-h-0">
          {/* Messages */}
          <div className="flex-1 flex flex-col overflow-y-auto p-4 gap-3">
            {messages.length === 0 && (
              <div className="flex-1 flex flex-col items-center justify-center gap-2 text-muted text-sm">
                <span>Ask anything about your portfolio</span>
                <div className="flex flex-wrap gap-2 justify-center mt-2">
                  {chips.map(c => (
                    <button key={c} onClick={() => send(c)}
                      className="text-xs px-3 py-1.5 rounded-full border border-border
                                 hover:border-accent hover:text-white transition-colors
                                 bg-transparent text-muted cursor-pointer">
                      {c}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {messages.map((m, i) => (
              <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                <div className={`max-w-[85%] rounded-lg px-3 py-2 text-sm leading-relaxed
                  ${m.role === 'user'
                    ? 'bg-accent text-white'
                    : 'bg-surface border border-border text-white'}`}>
                  {m.loading
                    ? <span className="flex gap-1 items-center text-muted">
                        <span className="animate-bounce">●</span>
                        <span className="animate-bounce [animation-delay:0.1s]">●</span>
                        <span className="animate-bounce [animation-delay:0.2s]">●</span>
                      </span>
                    : <>
                        <span className="whitespace-pre-wrap">{m.text}</span>
                        {m.requiresApproval && m.approvalContext && !m.approvalResolved && (
                          <ApprovalCard
                            approvalContext={m.approvalContext}
                            onResolved={(decision, resultText) => {
                              setMessages(prev => {
                                const copy = [...prev]
                                copy[i] = { ...copy[i], approvalResolved: decision }
                                return [
                                  ...copy,
                                  { role: 'agent', text: resultText },
                                ]
                              })
                            }}
                          />
                        )}
                        {m.approvalResolved && (
                          <div className={`mt-2 text-xs font-medium ${
                            m.approvalResolved === 'approved' ? 'text-green-400' : 'text-red-400'
                          }`}>
                            {m.approvalResolved === 'approved' ? '✅ Trade approved' : '❌ Trade rejected'}
                          </div>
                        )}
                      </>
                  }
                </div>
              </div>
            ))}
            <div ref={bottomRef} />
          </div>

          {/* Live context panel */}
          <div className="w-[160px] border-l border-border p-3 flex flex-col gap-2 shrink-0 overflow-y-auto">
            <span className="text-xs text-muted font-medium">Live Context</span>
            {balance && (
              <div className="card !p-2 flex flex-col gap-1">
                <span className="text-xs text-muted">Equity</span>
                <span className="font-mono text-sm text-white">
                  ${balance.equity.toLocaleString('en-US', { maximumFractionDigits: 0 })}
                </span>
                <span className="text-xs text-muted mt-1">Cash</span>
                <span className="font-mono text-sm text-white">
                  ${balance.cash.toLocaleString('en-US', { maximumFractionDigits: 0 })}
                </span>
              </div>
            )}
            {activeTicker && (
              <div className="card !p-2 flex flex-col gap-1">
                <span className="text-xs text-muted">Active Ticker</span>
                <span className="font-mono text-sm font-medium text-accent">{activeTicker}</span>
              </div>
            )}
            <RiskStatus />
          </div>
        </div>

        {/* Input */}
        <div className="px-4 py-3 border-t border-border shrink-0">
          <div className="flex gap-2">
            <input
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && !e.shiftKey && send(input)}
              placeholder="Ask anything about your portfolio…"
              disabled={sending}
              className="flex-1 bg-surface border border-border rounded-lg px-3 py-2 text-sm
                         text-white placeholder-muted outline-none focus:border-accent transition-colors"
            />
            <button
              onClick={() => send(input)}
              disabled={sending || !input.trim()}
              className="btn-primary px-3 py-2 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              <Send size={16} />
            </button>
          </div>
        </div>
      </div>
    </>
  )
}
