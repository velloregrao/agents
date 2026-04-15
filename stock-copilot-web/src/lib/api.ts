const BASE = import.meta.env.VITE_API_URL ?? 'https://python-api.salmonsky-548aa144.eastus.azurecontainerapps.io'
const KEY  = import.meta.env.VITE_API_KEY  ?? ''

function headers(): HeadersInit {
  const h: HeadersInit = { 'Content-Type': 'application/json' }
  if (KEY) (h as Record<string, string>)['X-API-Key'] = KEY
  return h
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { headers: headers() })
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json()
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: headers(),
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json()
}

// ── Types ──────────────────────────────────────────────────────────────────────

export interface Balance {
  cash: number
  buying_power: number
  portfolio_value: number
  equity: number
  pnl_today: number
  pnl_today_pct: number
}

export interface Position {
  ticker: string
  quantity: number
  side: string
  entry_price: number
  current_price: number
  market_value: number
  unrealized_pnl: number
  unrealized_pnl_pct: number
}

// ── Raw portfolio response shape from GET /portfolio ──────────────────────────
interface PortfolioResponse {
  balance:   { cash: number; buying_power: number; portfolio_value: number
               equity: number; pnl_today: number; pnl_today_pct: number }
  positions: { positions: Position[] }
}

// ── IPO Watch types ────────────────────────────────────────────────────────────

export interface IpoWatchBreakdown {
  proxy_momentum:    number
  proxy_changes:     Record<string, number | null>
  news_sentiment:    number
  sentiment_label:   string
  s1_detected:       boolean
  roadshow_detected: boolean
  is_negative:       boolean
}

export interface IpoWatchProfileStatus {
  ticker:                   string
  company_name:             string
  estimated_listing_window: string
  proxy_stocks:             string[]
  last_score:               number | null
  last_signal:              string | null
  last_checked:             string | null
  breakdown:                IpoWatchBreakdown | null
}

export interface IpoWatchStatusResponse {
  profiles: IpoWatchProfileStatus[]
  count:    number
}

export interface IpoWatchProfile {
  ticker:                   string
  company_name:             string
  active:                   boolean
  estimated_listing_window: string
  estimated_valuation_usd:  number
  proxy_stocks:             string[]
}

export interface IpoWatchRunResult {
  ticker:       string
  company_name: string
  score:        number
  signal:       string
  breakdown:    IpoWatchBreakdown
  checked_at:   string
}

export interface IpoWatchRunResponse {
  run_at:           string
  profiles_checked: number
  results:          IpoWatchRunResult[]
  alerts_dispatched: Array<{
    ticker:     string
    signal:     string
    score:      number
    dispatched: string[]
    skipped:    string[]
  }>
}

// ── API surface ────────────────────────────────────────────────────────────────

export const api = {
  // GET /portfolio returns { balance, positions, open_trades, performance }
  portfolio: () => get<PortfolioResponse>('/portfolio'),

  // Convenience wrappers that unpack the combined response
  balance:   async (): Promise<Balance> => {
    const r = await get<PortfolioResponse>('/portfolio')
    return r.balance
  },
  positions: async (): Promise<{ positions: Position[] }> => {
    const r = await get<PortfolioResponse>('/portfolio')
    return r.positions
  },

  // ── Agent ──────────────────────────────────────────────────────────────────
  // POST /agent with { text, user_id, platform }
  sendMessage: (message: string, user_id = 'web-user') =>
    post<{ response: string; text?: string; requires_approval?: boolean; approval_context?: unknown }>(
      '/agent', { text: message, user_id, platform: 'web' }
    ),

  // ── Trade approval (ESCALATED trades from chat) ───────────────────────────
  approveDecision: (approval_id: string, decision: 'approve' | 'reject') =>
    post<{ response: string; text?: string }>('/agent/approve', { approval_id, decision }),

  // ── Rebalance ─────────────────────────────────────────────────────────────
  // POST /portfolio/rebalance/{plan_id}/execute — requires { user_id }
  approveRebalance: (plan_id: string, user_id = 'web-user') =>
    post(`/portfolio/rebalance/${plan_id}/execute`, { user_id }),
  // POST /portfolio/rebalance/{plan_id}/reject
  rejectRebalance: (plan_id: string) =>
    post(`/portfolio/rebalance/${plan_id}/reject`, {}),

  // ── Health ────────────────────────────────────────────────────────────────
  health: () => get<{ status: string }>('/health'),

  // ── IPO Watch ─────────────────────────────────────────────────────────────
  ipoWatchStatus: () => get<IpoWatchStatusResponse>('/ipo-watch/status'),
  ipoWatchRun:    (user_id = 'web-user') => post<IpoWatchRunResponse>('/ipo-watch/run', { user_id }),
  ipoWatchProfiles: () => get<{ profiles: IpoWatchProfile[] }>('/ipo-watch/profiles'),
}
