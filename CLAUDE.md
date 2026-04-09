# Agents project — Claude Code context

## What this project is

**Stock Copilot** — an AI-powered stock trading assistant with a multi-agent architecture,
semantic trade memory, human-in-the-loop approvals, and a web UI. Built for paper trading
(US equities via Alpaca Markets) with a path to live trading.

### Core technology stack
- **Anthropic Claude** (claude-sonnet-4-6 / claude-haiku-4-5-20251001) — reasoning backbone
- **Anthropic Managed Agents SDK** (v0.92.0) — persistent named agents with server-side state
- **ChromaDB** (local) / **Azure AI Search** (production) — vector store for semantic trade memory
- **Alpaca Markets API** (alpaca-py) — US equities execution, paper trading by default
- **Brave Search API** — market news and sentiment
- **Azure Bot Service / TeamsFx** — Microsoft Teams interface
- **FastAPI + uvicorn** — Python HTTP API (deployed to Azure Container Apps)
- **React 19 + Vite + Tailwind CSS** — web UI (deployed to Azure Static Web Apps)
- **MCP servers** — tool connectivity layer
- **SQLite** — local trade memory database; Azure Files volume in production

### Deployment
- **Python API**: Azure Container Apps (`python-api.salmonsky-548aa144.eastus.azurecontainerapps.io`)
- **Web UI**: Azure Static Web Apps
- **Teams bot**: Azure Bot Service
- **CI/CD**: GitHub Actions on push to `main` (`.github/workflows/deploy-python-api.yml`)
- **Container registry**: Azure Container Registry (ACR)

---

## Project structure

```
agents/
├── CLAUDE.md                              ← this file
├── AGENTS.md                              ← high-level project brief
├── .env.example                           ← all required env vars with descriptions
├── .agent_registry.json                   ← managed agent IDs (gitignored, local only)
│
├── orchestrator/                          ← brain of the system
│   ├── router.py                          ← intent classifier + pipeline coordinator
│   ├── risk_agent.py                      ← generator-critic risk gate (4 hard rules)
│   ├── managed_agents.py                  ← Anthropic managed agent registration
│   ├── session_orchestrator.py            ← session-based multi-agent pipeline
│   ├── vector_store.py                    ← ChromaDB semantic trade memory
│   ├── portfolio_optimizer.py             ← rebalancing plan generation + execution
│   ├── journal_agent.py                   ← trade journal sync + auto-embedding
│   ├── approval_manager.py                ← pending approval persistence
│   ├── alert_manager.py                   ← Teams / web alert dispatch
│   ├── mtf_analysis.py                    ← multi-timeframe technical analysis
│   ├── scheduler.py                       ← APScheduler cron jobs
│   └── contracts.py                       ← shared data types (AgentMessage etc.)
│
├── stock-analysis-agent/                  ← Python API container
│   ├── pyproject.toml                     ← dependencies (anthropic>=0.92.0, chromadb>=1.5.0)
│   ├── Dockerfile                         ← build context is repo root
│   └── src/stock_agent/
│       ├── api.py                         ← FastAPI app, all HTTP endpoints
│       ├── agent.py                       ← Claude analysis agent (RSI/EMA/VWAP)
│       ├── alpaca_tools.py                ← Alpaca SDK wrappers (positions, orders, cancel)
│       ├── memory.py                      ← SQLite trade memory store
│       ├── trading_agent.py               ← order execution via Alpaca
│       ├── reflection.py                  ← weekly lesson extraction
│       ├── research.py                    ← Brave search + Claude research pipeline
│       └── watchlist.py                   ← per-user watchlist management
│
├── stock-copilot-web/                     ← React web UI
│   ├── vite.config.ts                     ← proxy: /api → 127.0.0.1:8000 (dev)
│   ├── .env.production                    ← VITE_API_URL (Azure Container App URL)
│   └── src/
│       ├── App.tsx                        ← root, screen routing, plan state
│       ├── lib/api.ts                     ← typed API client (sendMessage, approveDecision, etc.)
│       └── components/
│           ├── ChatDrawer.tsx             ← slide-in chat with inline ApprovalCard
│           ├── Dashboard.tsx              ← portfolio stats + positions table + alerts
│           ├── TradeApprovalModal.tsx     ← rebalance plan review + approve/reject
│           ├── SignalsFeed.tsx            ← live signal cards (RSI, EMA, momentum)
│           ├── Journal.tsx               ← trade journal + weekly digest
│           ├── Settings.tsx              ← target allocation editor (donut chart)
│           ├── NavBar.tsx                ← top nav
│           └── ActionBar.tsx             ← quick-action chips
│
├── stock-copilot-agent/                   ← Microsoft Teams bot (TypeScript)
│   ├── index.ts                           ← Restify server, port 3978
│   └── teamsBot.ts                        ← Bot Framework message handler
│
├── mcp-servers/                           ← MCP tool connectivity layer
│   ├── memory/                            ← trade memory MCP server
│   ├── news/                              ← Brave search MCP server
│   ├── orchestrator/                      ← orchestrator MCP server
│   ├── portfolio/                         ← Alpaca portfolio MCP server
│   └── stock-data/                        ← price + technicals MCP server
│
├── scripts/                               ← one-time setup + dev utilities
│   ├── register_agents.py                 ← register managed agents with Anthropic API
│   ├── setup_vector_db.py                 ← initialize ChromaDB + backfill from SQLite
│   └── seed_test_trades.py                ← insert 28 synthetic trades for local testing
│
├── docs/
│   └── vector-db-agents-guide.md          ← 4-phase implementation guide
│
├── tools/                                 ← slide deck generators (Node.js + PptxGenJS)
│   ├── create-deck.js                     ← Stock Copilot dark-theme deck (14 slides)
│   └── create-deck-gartner.js             ← Gartner brand deck (14 slides)
│
└── docker-compose.yml                     ← local: python-api (8000) + bot (3978)
```

---

## Full system architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│  User interfaces                                                         │
│                                                                          │
│  Web UI (React/Vite)          Microsoft Teams bot                        │
│  Azure Static Web Apps        Azure Bot Service / TeamsFx                │
└──────────────┬────────────────────────────┬────────────────────────────┘
               │  POST /agent               │  Bot Framework
               ▼                            ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  FastAPI (stock_agent/api.py) — Azure Container App, port 8000           │
│  All requests → POST /agent → orchestrator/router.py                    │
└──────────────┬──────────────────────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  orchestrator/router.py                                                  │
│  Claude Haiku classifies intent → routes to handler                     │
│                                                                          │
│  Intents: analyze · research · trade · portfolio · reflect · monitor    │
│           watch · unwatch · watchlist · earnings · mtf · optimize       │
│           digest · cancel · help                                         │
└──────┬───────────────┬──────────────────┬───────────────────────────────┘
       │               │                  │
       ▼               ▼                  ▼
  ANALYZE intent   TRADE intent      OPTIMIZE intent
       │               │                  │
       │    ┌──────────┴──────────┐        │
       │    │  Phase 4 pipeline   │        │
       │    │                     │        │
       │    │  session_           │        │
       │    │  orchestrator.py    │        │
       │    │  run_analysis_      │        │
       │    │  session()          │        │
       │    │  ↓                  │        │
       │    │  Managed Analysis   │        │
       │    │  Agent              │        │
       │    │  (claude-sonnet-4-6)│        │
       │    │  + vector context   │        │
       │    └──────────┬──────────┘        │
       │               │                   │
       ▼               ▼                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  orchestrator/vector_store.py (ChromaDB)                                 │
│  query_similar_trades() → top-5 semantically similar historical trades  │
│  Collections: trade_memories · market_knowledge · risk_decisions         │
│  Embedding: all-MiniLM-L6-v2 (384-dim, local, free)                    │
└──────────────────────────────────────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  orchestrator/risk_agent.py — MANDATORY gate, never bypassed             │
│  evaluate_proposal(ticker, proposed_qty, side)                           │
│                                                                          │
│  Rule 1: Daily loss circuit breaker  (BLOCK if down >2% today)          │
│  Rule 2: Position size limit         (RESIZE if >5% of equity)          │
│  Rule 3: Sector concentration        (ESCALATE if sector >25% equity)   │
│  Rule 4: Correlation guard           (ESCALATE if correlated pair held) │
│                                                                          │
│  Verdicts: APPROVED · RESIZE · BLOCK · ESCALATE                         │
└──────────────────────────────────────────────────────────────────────────┘
               │
       ┌───────┴────────────────────────┐
       │ APPROVED / RESIZE              │ ESCALATE / BLOCK
       ▼                                ▼
  stock_agent/                    approval_manager.py
  trading_agent.py                → web UI ApprovalCard
  → Alpaca Markets API            → Teams Adaptive Card
  → paper trade executed          → human decides approve/reject
```

---

## The single most important rule in this codebase

**Never call trade.py / trading_agent.py directly from the orchestrator.**
Every trade proposal MUST pass through `orchestrator/risk_agent.py →
evaluate_proposal()` before any order is submitted to Alpaca.

The session orchestrator's managed risk agent provides narrative context but
does NOT replace the hard-coded rule checks in risk_agent.py.

---

## Multi-agent system — full detail

### Three Anthropic managed agents (registered via scripts/register_agents.py)

| Agent name | Agent ID (in .agent_registry.json) | Model | Role |
|---|---|---|---|
| stock-copilot-analysis | agent_011CZt6hfirddnddEEn1LNZN | claude-sonnet-4-6 | Technical + fundamental analysis with vector context |
| stock-copilot-risk | agent_011CZt6hbrBm4ufAkrqj3jEn | claude-sonnet-4-6 | Risk narrative generation (supplements hard rules) |
| stock-copilot-portfolio | agent_011CZt6hjmRxp86iXRDCTv9V | claude-sonnet-4-6 | Portfolio optimization and rebalancing |

Environment ID: `env_012Gw4anjjVvbYwiU7DaUT7f`
Beta header: `managed-agents-2026-04-01`

### Agent registration (idempotent, one-time per environment)
```bash
source stock-analysis-agent/.env
stock-analysis-agent/.venv/bin/python scripts/register_agents.py
# Writes .agent_registry.json — gitignored, stays local
```

### Multi-agent patterns in use

| Pattern | Where used |
|---|---|
| Generator + critic | risk_agent.py intercepts every analysis agent proposal |
| Sequential pipeline | vector context → analysis session → risk gate → execution |
| Human-in-the-loop | Web UI ApprovalCard + Teams Adaptive Cards for ESCALATE |
| Parallel fan-out/gather | run_parallel_watchlist_scan() — asyncio.gather() across N tickers |
| Coordinator/dispatcher | router.py routes 15 intents to specialist handlers |
| Iterative refinement | Portfolio optimizer: propose → risk check → resize → execute |

### Model tiering (cost optimisation)

```python
HAIKU  = "claude-haiku-4-5-20251001"   # intent classification, formatting (~10% of calls)
SONNET = "claude-sonnet-4-6"           # analysis, risk narrative, trade thesis (~90% of calls)
```
Mixing models reduces cost 40–60% vs running Sonnet for everything.

---

## Vector store — semantic trade memory

### File: orchestrator/vector_store.py

Three ChromaDB collections, persisted at `~/.chromadb/stock_copilot/` (local)
or Azure AI Search (production, via `VECTOR_BACKEND=azure`).

| Collection | What's stored | Key metadata fields |
|---|---|---|
| trade_memories | Every closed trade | ticker, side, rsi, ema_signal, pnl_pct, hold_days, entry_date |
| market_knowledge | News articles embedded per ticker | ticker, title, date |
| risk_decisions | BLOCK/ESCALATE decisions | ticker, verdict, narrative, rule |

### Embedding model
- `all-MiniLM-L6-v2` (ChromaDB default, 384-dimensional, runs locally, free)
- Optional: `text-embedding-3-small` (OpenAI) if `OPENAI_API_KEY` is set

### How vector context flows
1. User types `analyze AAPL` or `buy NVDA`
2. `query_similar_trades(ticker, rsi, side, n=5)` returns top-5 semantically similar past trades
3. Results formatted as a `### Historical context` markdown block
4. Prepended to the analysis output (analyze intent) or injected into the managed agent session (trade intent)
5. On trade close: `journal_agent.py` calls `embed_closed_trade()` automatically — the memory grows

### Setup
```bash
# Initialize collections + backfill from SQLite
stock-analysis-agent/.venv/bin/python scripts/setup_vector_db.py

# Seed 28 synthetic trades for local testing
stock-analysis-agent/.venv/bin/python scripts/seed_test_trades.py
```

---

## Generator-critic pattern (risk agent)

File: `orchestrator/risk_agent.py`
Entry point: `evaluate_proposal(ticker, proposed_qty, side)`

```
Analysis agent (generator) → produces trade proposal
         ↓
Risk agent (critic) runs 4 rules in order:
  Rule 1: Daily loss circuit breaker  — BLOCK all trading if down >RISK_DAILY_LOSS_HALT
  Rule 2: Position size limit         — RESIZE if single position >RISK_MAX_POSITION_PCT
  Rule 3: Sector concentration        — ESCALATE if GICS sector >RISK_MAX_SECTOR_CONC_PCT
  Rule 4: Correlation guard           — ESCALATE if correlated pair already held
         ↓
Returns RiskResult(verdict, adjusted_qty, reason, narrative)
```

Config (env var overrides):
```
RISK_MAX_POSITION_PCT     default 0.05   (5% of equity per position)
RISK_MAX_SECTOR_CONC_PCT  default 0.25   (25% of equity per GICS sector)
RISK_DAILY_LOSS_HALT      default -0.02  (-2% portfolio loss halts all trading)
```

---

## Web UI — key component details

### ChatDrawer.tsx
- Slide-in drawer (480px wide) with chat history + live context panel
- `ApprovalCard` component renders inline when `requires_approval: true` in API response
- Differentiates between two approval types:
  - `alert_type: "rebalance"` → calls `POST /portfolio/rebalance/{plan_id}/execute`
  - Single trade ESCALATE → calls `POST /agent/approve` with `{ approval_id, decision }`
- Approval buttons: green Approve + red Reject, disabled while request is in flight
- After decision: buttons replaced by ✅/❌ badge, result appended as new message

### api.ts — full API surface
```typescript
api.portfolio()                              // GET /portfolio
api.sendMessage(text, user_id?)              // POST /agent
api.approveDecision(approval_id, decision)   // POST /agent/approve
api.approveRebalance(plan_id, user_id?)      // POST /portfolio/rebalance/{id}/execute
api.rejectRebalance(plan_id)                 // POST /portfolio/rebalance/{id}/reject
api.health()                                 // GET /health
```

### Vite proxy
- Dev: `/api` → `http://127.0.0.1:8000` (set in `vite.config.ts`)
- Production: `VITE_API_URL` in `.env.production` → Azure Container App URL
- To override in dev: `VITE_API_TARGET=http://127.0.0.1:8000 npm run dev`

---

## FastAPI endpoints (stock_agent/api.py)

| Method | Path | Description |
|---|---|---|
| POST | /agent | Main entry — all chat messages, routes via router.py |
| POST | /agent/approve | Approve or reject an ESCALATED trade (`decision: "approve"\|"reject"`) |
| GET | /portfolio | Positions, balance, P&L, open trades |
| POST | /portfolio/rebalance | Generate rebalancing plan (returns plan_id) |
| POST | /portfolio/rebalance/{id}/execute | Execute an approved rebalancing plan |
| POST | /portfolio/rebalance/{id}/reject | Reject / cancel a rebalancing plan |
| GET | /health | Liveness probe |
| GET | /health/deep | Deep health check (Alpaca + DB connectivity) |
| GET | /agent/pending | List pending ESCALATED trade approvals |

---

## Router intents (orchestrator/router.py)

| Intent | Trigger phrases | Handler |
|---|---|---|
| analyze | "analyze AAPL", "technicals on NVDA" | Phase 2: vector context + run_analysis() |
| research | "research MSFT", "buy/hold/sell on AMD" | Brave search + Claude thesis |
| trade | "buy AAPL", "trade NVDA" | Phase 4: managed agent + risk gate + execution |
| portfolio | "portfolio", "positions", "balance" | _format_portfolio() |
| optimize | "optimize", "rebalance" | build_rebalance_plan() → approval |
| cancel | "cancel all orders", "cancel orders" | cancel_all_orders() |
| reflect | "reflect", "lessons learned" | weekly reflection via Claude |
| monitor | "monitor", "check positions" | open position review |
| watch | "watch AAPL NVDA" | add to watchlist |
| unwatch | "unwatch AAPL" | remove from watchlist |
| watchlist | "my watchlist" | show watchlist |
| earnings | "earnings NVDA" | earnings calendar + pre-earnings thesis |
| mtf | "MTF AAPL", "multi-timeframe" | 15m + daily + weekly analysis |
| digest | "digest", "weekly summary" | journal digest |
| help | "help", "what can you do" | capability list |

---

## Session orchestrator pipeline (orchestrator/session_orchestrator.py)

### Trade pipeline (run_trade_pipeline)
```
1. _get_vector_context(ticker)
   → query_similar_trades() from ChromaDB → top-5 similar trades

2. run_analysis_session(ticker, analysis_agent_id, vector_context)
   → client.beta.sessions.create(agent=agent_id, environment_id=env_id)
   → Claude Sonnet analysis with historical context injected

3. run_risk_session(ticker, qty, side, risk_agent_id, analysis_result)
   → AI-generated risk narrative (supplements hard rules in risk_agent.py)

4. Return verdict + narrative to router
   → router still calls evaluate_proposal() for hard rule enforcement
```

### Parallel watchlist scan (run_parallel_watchlist_scan)
```python
asyncio.gather(*[_scan_ticker_async(t, agent_id, semaphore) for t in tickers])
# Each ticker: asyncio.to_thread(run_analysis_session, ...) — SDK is synchronous
# max_concurrency=5 semaphore to stay within API rate limits
```

---

## Alpaca tools (stock_agent/alpaca_tools.py)

Key functions:
```python
get_account_balance()         # equity, cash, buying_power, P&L
get_positions()               # all open positions with unrealized P&L
get_current_price(ticker)     # latest quote via IEX feed
get_open_orders()             # open buy orders (for wash-trade detection)
get_order_history(n=10)       # recent order history
cancel_order(order_id)        # cancel single order
cancel_all_orders()           # cancel all open orders (both sides), returns summary
close_position(ticker)        # close entire position at market
place_order(ticker, qty, side, order_type)  # market or limit order
```

Clients:
```python
TradingClient(api_key, secret_key, paper=True)         # orders, positions, account
StockHistoricalDataClient(api_key, secret_key)         # bars, quotes
```

Always use `feed="iex"` (free tier) unless `ALPACA_FEED=sip` is set.

---

## Critical: frameworks Claude Code does not know

### alpaca-py SDK (NOT alpaca-trade-api which is deprecated)
Full reference: `stock-trading-skill/references/alpaca-api.md`

Key imports:
```python
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest, GetOrdersRequest
from alpaca.trading.enums import OrderSide, TimeInForce, QueryOrderStatus
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest, StockLatestQuoteRequest
from alpaca.data.timeframe import TimeFrame
```

### Anthropic Managed Agents SDK (v0.92.0)
```python
client = anthropic.Anthropic(api_key=...)

# Create a persistent agent
agent = client.beta.agents.create(
    model="claude-sonnet-4-6",
    name="my-agent",
    system="You are...",
    betas=["managed-agents-2026-04-01"],
)

# Create an environment (required for sessions)
env = client.beta.environments.create(
    name="my-env",
    betas=["managed-agents-2026-04-01"],
)

# Run a session
session = client.beta.sessions.create(
    agent=agent.id,            # accepts plain string
    environment_id=env.id,
    betas=["managed-agents-2026-04-01"],
)
```

Notes:
- `mcp_servers` on agents takes URL-based remote servers only (not local stdio)
- `tools` uses `{"type": "mcp_toolset", "mcp_server_name": name}` — server must be in agent's mcp_servers list
- Local stdio MCP servers cannot be passed as managed agent tools; invoke them separately

### OpenClaw / Moltbot (launched Nov 2025 — post training cutoff)
Self-hosted AI agent that loads modular SKILL.md plugins.
Our skill is at: `stock-trading-skill/`
Each skill: `SKILL.md` + `scripts/` (CLI, stdout = response) + `references/`

---

## Environment variables

```bash
# Core
ANTHROPIC_API_KEY          # required for all Claude calls
ALPACA_API_KEY             # Alpaca Markets key ID
ALPACA_API_SECRET          # Alpaca Markets secret
ALPACA_BASE_URL            # https://paper-api.alpaca.markets (default)
BRAVE_API_KEY              # Brave Search API

# Bot
BOT_ID                     # Azure Bot app ID
BOT_PASSWORD               # Azure Bot app password
BOT_TENANT_ID              # Azure tenant ID

# API security
AGENT_API_KEY              # X-API-Key header (leave empty for open local dev)

# Database
DB_PATH                    # SQLite path (default: iCloud/Projects/data/trading_memory.db)
                           # Local dev: /path/to/agents/data/trading_memory.db

# Vector store
VECTOR_BACKEND             # "chroma" (local dev) or "azure" (production)
AZURE_SEARCH_ENDPOINT      # https://your-service.search.windows.net
AZURE_SEARCH_KEY           # Azure AI Search admin key
AZURE_SEARCH_INDEX         # stock-copilot

# Risk agent overrides
RISK_MAX_POSITION_PCT      # default 0.05  (5%)
RISK_MAX_SECTOR_CONC_PCT   # default 0.25  (25%)
RISK_DAILY_LOSS_HALT       # default -0.02 (-2%)
```

---

## Local development — startup commands

```bash
# Terminal 1 — Python API
cd /path/to/agents
source stock-analysis-agent/.env
stock-analysis-agent/.venv/bin/python \
  -m uvicorn stock_agent.api:app \
  --app-dir stock-analysis-agent/src \
  --host 0.0.0.0 --port 8000 --reload

# Terminal 2 — Web UI
cd stock-copilot-web
npm run dev
# Opens at http://localhost:5174 (or 5173 if available)

# One-time setup (new environment)
stock-analysis-agent/.venv/bin/python scripts/setup_vector_db.py
stock-analysis-agent/.venv/bin/python scripts/seed_test_trades.py   # dev only
source stock-analysis-agent/.env && \
  stock-analysis-agent/.venv/bin/python scripts/register_agents.py
```

---

## Test sequence (validates full stack)

Run these commands in the web UI or Teams bot in order:

1. `portfolio` — verifies Alpaca connection + DB
2. `analyze AAPL` — verifies vector context block appears above analysis
3. `buy MSFT` — verifies Phase 4 pipeline (managed agent → risk gate → execution)
4. `buy NVDA` — should ESCALATE (correlation guard: AMD already held)
   → click Approve → verifies human-in-the-loop approval flow
5. `optimize` — verifies rebalance plan generation
   → click Approve → verifies multi-trade execution
6. `cancel all orders` — cancels open orders before retry
7. `MTF AAPL` — verifies multi-timeframe analysis (15m / daily / weekly)

---

## Files to read before modifying specific areas

| Area | Read first |
|---|---|
| Risk / trade gate logic | orchestrator/risk_agent.py |
| Vector store / memory | orchestrator/vector_store.py |
| Managed agent registration | orchestrator/managed_agents.py |
| Session pipeline | orchestrator/session_orchestrator.py |
| Intent routing | orchestrator/router.py |
| Alpaca API calls | stock-trading-skill/references/alpaca-api.md |
| Web UI chat + approval | stock-copilot-web/src/components/ChatDrawer.tsx |
| Web UI API client | stock-copilot-web/src/lib/api.ts |
| Teams bot / Adaptive Cards | stock-copilot-agent/teamsBot.ts |
| FastAPI endpoints | stock-analysis-agent/src/stock_agent/api.py |
| Portfolio optimizer | orchestrator/portfolio_optimizer.py |
| Trade journal | orchestrator/journal_agent.py |

---

## Development conventions

- Always use paper trading (`ALPACA_BASE_URL=paper-api...`) unless told otherwise
- Every trade MUST pass through `risk_agent.evaluate_proposal()` — no exceptions
- Test modules standalone before wiring into orchestrator
- Scripts: stdout = response, stderr = debug/logs, exit 0 = success
- No hardcoded credentials — always `os.environ` or `.env` via dotenv
- SQLite and ChromaDB are local-dev only — gitignored
- `.agent_registry.json` is gitignored — re-run `register_agents.py` per environment
- Never use `alpaca-trade-api` (deprecated) — always `alpaca-py`
- Model tiering: Haiku for routing/classification, Sonnet for analysis/reasoning

---

## Planned capabilities (not yet built)

1. **Azure AI Search adapter** in `vector_store.py`
   - Triggered by `VECTOR_BACKEND=azure`
   - Same public interface as ChromaDB implementation
   - Required before production vector store is persistent across deployments

2. **Watchlist monitor agent** (scheduled, not user-initiated)
   - Pattern: parallel fan-out/gather
   - Polls N tickers via `asyncio.gather()`, filters by scoring threshold
   - Pushes proactive Teams/web alerts

3. **Earnings intelligence agent**
   - Fetches earnings calendar → Brave research → thesis generation
   - Brave API key already configured

4. **Persistent volume for SQLite** in Azure Container Apps
   - Mount Azure Files share to `/data/`
   - Set `DB_PATH=/data/trading_memory.db` in Container App env

5. **Startup probe** for Container App health gate
   - Currently polls revision ready state (coarse)
   - TODO: add `/health/deep` as startup probe in Container App definition
