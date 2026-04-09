# Agents project — Codex context

## What this project is

An AI stock trading agent with a Microsoft Teams bot interface.
Multi-agent architecture built in Python using:
- Anthropic Codex (Codex-sonnet-4-6) as the reasoning backbone
- Alpaca Markets API for US equities execution (paper trading by default)
- Brave Search API for market news and sentiment
- Azure Bot Service / TeamsFx for the Teams interface
- MCP servers for tool connectivity

---

## Critical: frameworks Codex does not know

### OpenClaw / Moltbot (launched Nov 2025 — post training cutoff)
OpenClaw is a self-hosted AI agent that loads modular SKILL.md plugins.
It was originally named Clawdbot, then Moltbot, then OpenClaw.
Each skill is a directory with:
  - SKILL.md       (describes triggers, commands, setup to OpenClaw's LLM)
  - scripts/       (Python scripts called by OpenClaw via CLI, stdout = response)
  - references/    (markdown docs for additional context)

Script conventions:
  - Arguments via argparse (CLI flags only)
  - All output to stdout (OpenClaw reads this)
  - Errors/debug to stderr (never shown to user)
  - Exit code 0 = success, non-zero = failure
  - Fully non-interactive (no input() calls)
  - Stateless — OpenClaw handles memory

Our skill is at: stock-trading-skill/
Full skill format reference: stock-trading-skill/SKILL.md

### alpaca-py SDK (NOT alpaca-trade-api which is deprecated)
Full reference: stock-trading-skill/references/alpaca-api.md

Key clients:
  TradingClient(api_key, secret_key, paper=True)    → orders, positions, account
  StockHistoricalDataClient(api_key, secret_key)    → bars, quotes

Key imports:
  from alpaca.trading.client import TradingClient
  from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest
  from alpaca.trading.enums import OrderSide, TimeInForce
  from alpaca.data.historical import StockHistoricalDataClient
  from alpaca.data.requests import StockBarsRequest, StockLatestQuoteRequest
  from alpaca.data.timeframe import TimeFrame

Data feed: always use feed="iex" (free tier) unless ALPACA_FEED=sip is set.

---

## Project structure

```
agents/
├── AGENTS.md                          ← this file
├── .env.example                       ← all required env vars
├── orchestrator/
│   ├── router.py                      ← intent routing, pipeline coordination
│   └── risk_agent.py                  ← generator-critic risk checks
├── stock-analysis-agent/
│   └── scripts/
│       └── analyze.py                 ← RSI, EMA, VWAP, momentum score
├── stock-copilot-agent/               ← Teams bot (Azure Bot Service / TeamsFx)
├── stock-trading-skill/               ← OpenClaw skill
│   ├── SKILL.md                       ← OpenClaw skill descriptor
│   ├── scripts/
│   │   ├── analyze.py                 ← technical analysis
│   │   ├── trade.py                   ← order execution
│   │   ├── portfolio.py               ← account / positions / P&L
│   │   └── requirements.txt
│   └── references/
│       └── alpaca-api.md              ← Alpaca SDK patterns
├── mcp-servers/                       ← MCP tool connectivity layer
└── tools/                             ← shared utilities
```

---

## Architecture

```
Teams user
  ↓
stock-copilot-agent/          ← Azure Bot Service (Teams front-end)
  ↓
orchestrator/router.py        ← intent routing, model tiering
  ↓
orchestrator/risk_agent.py    ← ALWAYS runs before any trade execution
  ↓
stock-analysis-agent/         ← Codex + Brave + Alpaca data → signal
  ↓
stock-trading-skill/scripts/trade.py  ← Alpaca order execution
  ↓
mcp-servers/                  ← MCP tool connectivity
```

---

## The single most important rule in this codebase

**Never call trade.py directly from the orchestrator.**
Every trade proposal MUST pass through orchestrator/risk_agent.py →
evaluate_proposal() before any order is submitted to Alpaca.

---

## Generator-critic pattern (risk agent)

File: orchestrator/risk_agent.py
Entry point: evaluate_proposal(ticker, proposed_qty, side)

The pattern:
  1. Analysis agent (generator) produces a trade proposal
  2. Risk agent (critic) runs 4 rule checks
  3. On RESIZE: qty is adjusted and rules re-run (max 1 iteration)
  4. Returns RiskResult with verdict + narrative

Verdicts:
  APPROVED  → execute with (possibly adjusted) adjusted_qty
  RESIZE    → qty was auto-adjusted, execute with adjusted_qty
  BLOCK     → do not execute, log reason, no Teams alert needed
  ESCALATE  → post Teams Adaptive Card, await human approval before executing

Four rules (run in this order):
  1. Daily loss circuit breaker  — halt all trading if portfolio down >RISK_DAILY_LOSS_HALT on the day
  2. Position size limit         — no single position > RISK_MAX_POSITION_PCT of equity (resize if over)
  3. Sector concentration        — no GICS sector > RISK_MAX_SECTOR_CONC_PCT of equity (escalate if over)
  4. Correlation guard           — escalate if proposed ticker is in a known correlated pair with a held stock

Config (all overridable via env vars):
  RISK_MAX_POSITION_PCT     default 0.05   (5%)
  RISK_MAX_SECTOR_CONC_PCT  default 0.25   (25%)
  RISK_DAILY_LOSS_HALT      default -0.02  (-2%)

Orchestrator usage pattern:
  result = evaluate_proposal(ticker="NVDA", proposed_qty=10, side="buy")
  if result.verdict == Verdict.APPROVED:
      # call trade.py with result.adjusted_qty
  elif result.verdict == Verdict.RESIZE:
      # call trade.py with result.adjusted_qty (already reduced)
  else:
      # post Teams Adaptive Card with result.reason and result.narrative

---

## Multi-agent patterns in use

| Pattern                | Where used                                                        |
|------------------------|-------------------------------------------------------------------|
| Generator + critic     | risk_agent.py intercepts every analysis agent proposal            |
| Sequential pipeline    | signal → risk check → execution (strict ordering, no skipping)   |
| Human-in-the-loop      | Teams Adaptive Cards for ESCALATE and BLOCK verdicts             |
| Parallel fan-out/gather| Watchlist monitor (planned): asyncio.gather() across N tickers   |
| Coordinator/dispatcher | orchestrator/router.py routes intents to specialist agents       |
| Iterative refinement   | Portfolio optimizer (planned): propose → critique → refine loop  |

---

## Planned capabilities (not yet built)

These are the next agents to build. Add them to orchestrator/router.py
as new intent handlers when implementing:

1. Watchlist monitor agent
   - Pattern: parallel fan-out/gather + evaluator-optimizer
   - Polls N tickers concurrently via asyncio.gather()
   - Filters signals through a scoring threshold
   - Pushes proactive Teams alerts when signals clear all gates
   - Cron/scheduled trigger, not user-initiated

2. Earnings intelligence agent
   - Pattern: sequential pipeline + iterative refinement
   - Fetches earnings calendar → Brave research per ticker → thesis generation
   - Brave API key already in .env.example

3. Multi-timeframe analysis agent
   - Pattern: parallel fan-out/gather + evaluator-optimizer
   - Runs same RSI/EMA analysis across 15m, daily, weekly simultaneously
   - Only signals when 2/3 or 3/3 timeframes are aligned
   - Uses TimeFrame.Minute with 15-unit intervals for intraday bars

4. Portfolio optimizer agent
   - Pattern: iterative refinement + generator-critic
   - Input: current positions + target allocation config (YAML)
   - Output: rebalancing trade set, always requires Teams approval

5. Trade journal + learning agent
   - Pattern: sequential pipeline + coordinator-dispatcher
   - Triggered on every trade close event
   - SQLite schema: trades(id, ticker, entry_price, exit_price, entry_date,
     exit_date, signal_score, momentum_score, rsi, outcome_pnl, thesis_text)
   - Weekly pattern analysis surfaced to Teams

---

## Model tiering

Use the cheaper/faster model for routing and formatting.
Use the smarter model for analysis, reasoning, and narrative generation.

  fast_model  = "Codex-haiku-4-5-20251001"   # routing, classification, formatting
  smart_model = "Codex-sonnet-4-6"            # analysis, risk narrative, trade thesis

Mixing models reduces cost 40-60% vs running Sonnet for everything.

---

## Environment variables

See .env.example for all keys. Key ones:

  ANTHROPIC_API_KEY          required for all Codex calls
  ALPACA_API_KEY             Alpaca Markets key ID
  ALPACA_API_SECRET          Alpaca Markets secret
  ALPACA_BASE_URL            https://paper-api.alpaca.markets (paper, default)
                             https://api.alpaca.markets (live — use with caution)
  BOT_ID                     Azure Bot app ID
  BOT_PASSWORD               Azure Bot app password
  BOT_TENANT_ID              Azure tenant ID
  BRAVE_API_KEY              Brave Search API key

Risk agent config (optional overrides):
  RISK_MAX_POSITION_PCT
  RISK_MAX_SECTOR_CONC_PCT
  RISK_DAILY_LOSS_HALT

---

## Development conventions

- Always use paper trading (ALPACA_BASE_URL=paper-api...) unless told otherwise
- Test every script standalone before wiring into orchestrator:
    python stock-trading-skill/scripts/analyze.py --ticker AAPL
    python stock-trading-skill/scripts/portfolio.py
    python stock-trading-skill/scripts/trade.py --action buy --ticker AAPL --qty 1
- Add a __main__ test block to every new module for standalone testing
- Scripts output to stdout, debug/log to stderr
- No hardcoded credentials — always read from os.environ
- SQLite trade log is local dev only (excluded from git via .gitignore)
- Never use alpaca-trade-api (deprecated) — always alpaca-py

---

## Files to read before modifying specific areas

| Area                        | Read first                                         |
|-----------------------------|----------------------------------------------------|
| Risk / trade gate logic     | orchestrator/risk_agent.py                         |
| New OpenClaw skill          | stock-trading-skill/SKILL.md (format reference)    |
| Alpaca API calls            | stock-trading-skill/references/alpaca-api.md       |
| Teams bot / Adaptive Cards  | stock-copilot-agent/ entry point                   |
| MCP server additions        | mcp-servers/ README or existing server files       |
| Analysis / technical logic  | stock-analysis-agent/scripts/analyze.py            |
