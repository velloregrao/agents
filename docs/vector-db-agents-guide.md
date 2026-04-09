# Stock Copilot: Vector DB + Managed Agents Implementation Guide

A step-by-step guide to upgrading Stock Copilot with ChromaDB semantic memory
and Anthropic managed agents.

---

## Overview

This guide adds two capabilities to the existing system:

1. **Semantic memory** — ChromaDB stores embeddings of past trades, news, and
   risk decisions so agents can recall similar historical situations at inference
   time rather than relying solely on the SQLite trade log.

2. **Managed agents** — Anthropic's `client.beta.agents` API registers the
   analysis, risk, and portfolio agents as persistent server-side entities with
   defined system prompts and MCP tool bindings. Sessions (`client.beta.sessions`)
   carry state across agent boundaries.

### Architecture after this guide

```
Teams user
  ↓
stock-copilot-agent/     ← Azure Bot Service (unchanged)
  ↓
orchestrator/router.py   ← intent routing (unchanged)
  ↓
orchestrator/session_orchestrator.py   ← NEW: session pipeline
  ├── vector_store.py    — query_similar_trades() injects context
  ├── managed_agents.py  — get_or_create_agents() loads agent IDs
  ├── run_analysis_session()  → Anthropic managed analysis agent
  └── run_risk_session()      → Anthropic managed risk agent
  ↓
stock-trading-skill/scripts/trade.py   ← Alpaca execution (unchanged)
```

### Files added by this guide

| File | Purpose |
|------|---------|
| `orchestrator/vector_store.py` | ChromaDB collections + embed/query functions |
| `orchestrator/managed_agents.py` | Agent registration + registry I/O |
| `orchestrator/session_orchestrator.py` | Session pipeline orchestration |
| `scripts/setup_vector_db.py` | One-time setup script |
| `scripts/register_agents.py` | One-time agent registration script |

---

## Phase 1: Vector DB Setup

### Goal

Stand up a local ChromaDB instance with three collections and backfill
`trade_memories` from the existing SQLite trading history. After this phase
the system has persistent semantic memory of every closed trade.

### Prerequisites

- Python 3.11+
- `stock-analysis-agent/.env` with `ANTHROPIC_API_KEY` set
- SQLite DB at `~/Library/Mobile Documents/com~apple~CloudDocs/Projects/data/trading_memory.db`
  (created by `stock_agent.memory.initialize_db()`)
- Optional: `OPENAI_API_KEY` in `.env` for higher-quality embeddings

### Steps

**1. Install chromadb**

```bash
pip install chromadb
```

If you want OpenAI embeddings (text-embedding-3-small, recommended):

```bash
pip install chromadb openai
# Then add to stock-analysis-agent/.env:
# OPENAI_API_KEY=sk-...
```

**2. Run the setup script**

```bash
cd /Users/velloregrao/Projects/agents
python scripts/setup_vector_db.py
```

Expected output:

```
Step 1: Checking chromadb installation...
  OK — chromadb 0.6.x
  OPENAI_API_KEY detected — will use text-embedding-3-small

Step 2: Initializing ChromaDB collections...
[vector_store] collection ready: trade_memories
[vector_store] collection ready: market_knowledge
[vector_store] collection ready: risk_decisions
  OK — all three collections ready

Step 3: Backfilling trade_memories from SQLite...
  SQLite DB: ~/Library/.../trading_memory.db
[vector_store] backfill from SQLite: ...
[vector_store] backfill complete — 42 total, 42 embedded, 0 skipped
  Total closed trades: 42
  Newly embedded:      42

Step 4: Collection summary:
  trade_memories                    42 records
  market_knowledge                   0 records
  risk_decisions                     0 records
```

**3. Verify with the vector_store test block**

```bash
python orchestrator/vector_store.py
```

This runs a synthetic embed-then-query cycle for all three collections.

### Code integration points

**Where to call `embed_closed_trade()` automatically:**

When `journal_agent.sync_closed_trades()` closes a trade, embed it immediately
so future analysis sessions benefit from the new data point.

Modify `orchestrator/journal_agent.py` — in the `sync_closed_trades()` function,
after the `close_trade()` call returns success, add:

```python
# After the successful close_trade() block (around line 120):
try:
    from orchestrator.vector_store import embed_closed_trade
    embed_closed_trade({
        **trade,
        "pnl":       result.get("pnl"),
        "pnl_pct":   result.get("pnl_pct"),
        "hold_days": result.get("hold_days"),
    })
except Exception as vec_exc:
    print(f"[journal] vector embed failed for {ticker}: {vec_exc}", file=sys.stderr)
```

**Where to call `embed_news_article()` automatically:**

In `stock_agent/research.py` (or wherever Brave Search results are consumed),
embed each article after fetching:

```python
from orchestrator.vector_store import embed_news_article

for article in brave_results:
    embed_news_article(
        ticker=ticker,
        title=article["title"],
        body=article.get("description", ""),
        date=article.get("published_date", ""),
    )
```

### Verify

```bash
python scripts/setup_vector_db.py --verbose
```

The `trade_memories` count should match the number of CLOSED trades in SQLite.
If both are zero, place and close a paper trade first:

```bash
python stock-trading-skill/scripts/trade.py --action buy --ticker AAPL --qty 1
# (close it via Alpaca dashboard or the sell command)
# Then:
python scripts/setup_vector_db.py
```

---

## Phase 2: Enriching Agents with Vector Context

### Goal

Make the analysis agent aware of similar historical trades before it produces
its signal. A prompt prefix summarising the 5 most similar past trades is
injected into every analysis session, calibrating confidence and preventing
repeated mistakes.

### Prerequisites

- Phase 1 complete (vector_store collections initialized and populated)
- `orchestrator/vector_store.py` importable

### Steps

**1. Understand the context format**

`query_similar_trades(ticker, rsi, side, n=5)` returns up to 5 dicts:

```python
{
    "doc_id":   "abc123...",
    "document": "Trade: BUY AAPL | Entry RSI: 28.5 | ...",
    "metadata": {
        "ticker":      "AAPL",
        "side":        "BUY",
        "entry_rsi":   28.5,
        "ema_signal":  "bullish",
        "outcome_pct": 5.71,
        "hold_days":   10,
        ...
    },
    "distance": 0.12,
}
```

`session_orchestrator._format_vector_context()` converts this list into a
markdown block that is prepended to the analysis user message.

**2. Use the session orchestrator for analysis calls**

The existing `run_analysis()` call in `router.py` (around line 438) currently
calls `stock_agent.agent.run_analysis()` directly. To inject vector context,
route through `session_orchestrator.run_analysis_session()` instead.

Modify `orchestrator/router.py`:

```python
# BEFORE (line 438):
if intent == "analyze" and tickers:
    return run_analysis(tickers[0]), False, None

# AFTER:
if intent == "analyze" and tickers:
    try:
        from orchestrator.session_orchestrator import run_analysis_session, _get_vector_context
        from orchestrator.managed_agents import get_or_create_agents
        agent_ids   = get_or_create_agents()
        vector_ctx  = _get_vector_context(tickers[0])
        result      = run_analysis_session(tickers[0], agent_ids["analysis"], vector_ctx)
        return result["analysis"], False, None
    except Exception:
        # Graceful fallback to direct call if sessions unavailable
        return run_analysis(tickers[0]), False, None
```

**3. Surface RSI for better vector queries**

For best semantic matching, pass the live RSI into `_get_vector_context()`.
You can fetch it cheaply before the session:

```python
from stock_agent.tools import get_technical_indicators
tech  = get_technical_indicators(ticker)
rsi   = tech.get("rsi", 50.0)
vector_ctx = _get_vector_context(ticker, rsi=rsi, side="BUY")
```

**4. Backfill new trades as they close**

The integration in Phase 1 (patching `journal_agent.sync_closed_trades()`)
ensures the vector store grows continuously. No further work is needed here.

### Verify

Run a manual analysis and check that "Historical Similar Trades" appears in the
analysis text (if there are trades in the vector store):

```bash
python orchestrator/session_orchestrator.py --ticker AAPL
```

The console output should include:

```
[session_orchestrator] AAPL — 5 similar trades from vector store
[session_orchestrator] analysis complete — 312 tokens
```

---

## Phase 3: Registering Managed Agents

### Goal

Register the three Stock Copilot agents (analysis, risk, portfolio) as
persistent managed agents with the Anthropic API. This is a one-time setup
step per environment. Registered agents retain their system prompts and MCP
tool bindings server-side.

### Prerequisites

- `anthropic>=0.92.0` installed
- `ANTHROPIC_API_KEY` with managed-agents beta access
- MCP servers running (the `mcp-servers/` directory contains the five servers:
  `memory`, `news`, `orchestrator`, `portfolio`, `stock-data`)

### Steps

**1. Upgrade the Anthropic SDK**

```bash
pip install -U "anthropic>=0.92.0"
python -c "import anthropic; print(anthropic.__version__)"
```

**2. Run the registration script**

```bash
python scripts/register_agents.py
```

Expected output:

```
=== Stock Copilot Agent Registration ===

Checking prerequisites...
  ANTHROPIC_API_KEY: sk-ant-...
  anthropic SDK: 0.92.0

Registering agents with Anthropic API...

[managed_agents] registering missing agents: {'analysis', 'risk', 'portfolio'}
[managed_agents] registered analysis agent: agt_01AbcDef...
[managed_agents] registered risk agent: agt_02GhiJkl...
[managed_agents] registered portfolio agent: agt_03MnoPqr...

Registration complete. Agent IDs saved to: .agent_registry.json

  analysis        → agt_01AbcDef...
  risk            → agt_02GhiJkl...
  portfolio       → agt_03MnoPqr...
```

**3. Inspect the registry**

```bash
python scripts/register_agents.py --show
```

The `.agent_registry.json` file at the project root looks like:

```json
{
  "analysis":  "agt_01AbcDef...",
  "risk":      "agt_02GhiJkl...",
  "portfolio": "agt_03MnoPqr..."
}
```

**4. Re-registration (if needed)**

```bash
python scripts/register_agents.py --force
```

Use `--force` when you have changed system prompts and want to push the update.

### Code integration points

**`get_or_create_agents()` is the correct call site.**

Any module that needs an agent ID should import and call `get_or_create_agents()`:

```python
from orchestrator.managed_agents import get_or_create_agents
ids = get_or_create_agents()
analysis_agent_id  = ids["analysis"]
risk_agent_id      = ids["risk"]
portfolio_agent_id = ids["portfolio"]
```

This is already done inside `session_orchestrator.run_trade_pipeline()` so the
router itself does not need to be aware of agent IDs directly.

**Beta header requirement:**

Every API call that uses the managed-agents feature must include the header:
```
anthropic-beta: managed-agents-2026-04-01
```

This is handled automatically by `managed_agents._create_agent()` and
`session_orchestrator._run_session()` via the `extra_headers` parameter.

### Verify

```bash
python scripts/register_agents.py --show
```

All three roles should appear with `agt_` prefixed IDs. If you see
`RuntimeError: client.beta.agents is not available`, the SDK version is too old
or the beta flag is not enabled on your account.

---

## Phase 4: Session Orchestration

### Goal

Replace router.py's direct function calls with session-based pipelines that
carry state and context across agent boundaries. The `run_trade_pipeline()`
function becomes the canonical entry point for trade decisions, superseding the
inline risk-gate block in `_dispatch_full()`.

### Prerequisites

- Phases 1–3 complete
- `.agent_registry.json` populated with all three agent IDs
- ChromaDB initialized with at least the empty collections

### Steps

**1. Test the full pipeline standalone**

```bash
python orchestrator/session_orchestrator.py --ticker NVDA --qty 3 --side buy
```

Expected flow (check stderr + stdout):

```
[managed_agents] all agents already registered — using registry
[session_orchestrator] NVDA — 3 similar trades from vector store
[session_orchestrator] analysis complete — 420 tokens
[session_orchestrator] risk verdict: APPROVED — all_rules_passed

Verdict:      APPROVED
Adjusted qty: 3
Vector used:  3 similar trades
Total tokens: 612
```

**2. Update the trade intent handler in router.py**

The current `trade` intent block (lines 444–507 in `router.py`) contains an
inline risk-gate loop. Replace it with a call to `run_trade_pipeline()` for
session-based orchestration while preserving the existing escalation and
approval flow:

```python
# In orchestrator/router.py, replace the `if intent == "trade" and tickers:` block:

if intent == "trade" and tickers:
    try:
        from orchestrator.session_orchestrator import run_trade_pipeline
        from orchestrator.approval_manager import store_pending

        blocked   = []
        escalated = []
        approved  = []

        for t in tickers:
            result = run_trade_pipeline(
                ticker=t,
                qty=max(
                    math.floor(
                        (get_account_balance().get("equity", 0) * 0.05)
                        / max(get_current_price(t).get("current_price", 1), 1)
                    ),
                    1,
                ),
                side="buy",
                user_id=user_id,
            )

            if result["verdict"] in ("APPROVED", "RESIZE"):
                approved.append((t, result["adjusted_qty"]))
            elif result["verdict"] == "BLOCK":
                blocked.append((t, result))
            elif result["verdict"] == "ESCALATE":
                escalated.append((t, result))

        lines = []
        for t, r in blocked:
            lines.append(f"BLOCKED {t} — {r['narrative']}")

        escalation_context = None
        for t, r in escalated:
            approval_id = store_pending(
                ticker=t, side="buy", qty=r["adjusted_qty"],
                reason=r["reason"], narrative=r["narrative"], user_id=user_id,
            )
            lines.append(f"ESCALATED {t} — {r['narrative']}")
            escalation_context = {
                "approval_id": approval_id,
                "ticker": t, "side": "buy",
                "qty": r["adjusted_qty"],
                "reason": r["reason"],
                "narrative": r["narrative"],
            }

        if approved:
            lines.append(run_trading_agent([t for t, _ in approved], raw_text or None))

        return (
            "\n\n".join(lines) or "No trades executed.",
            len(escalated) > 0,
            escalation_context,
        )

    except Exception as exc:
        # Graceful fallback to existing direct pipeline on session error
        print(f"[router] session pipeline failed, falling back: {exc}", file=sys.stderr)
        # ... existing trade block code as fallback ...
```

**3. Run a parallel watchlist scan**

```bash
python orchestrator/session_orchestrator.py --watchlist AAPL NVDA MSFT AMD TSLA
```

This uses `asyncio.gather()` with a semaphore (default concurrency=5) to scan
all five tickers in parallel. Each ticker gets its own session with vector
context.

**4. Wire parallel scan into the watchlist monitor**

In `orchestrator/watchlist_monitor.py`, the existing per-ticker analysis loop
can be replaced with `run_parallel_watchlist_scan()`:

```python
# In watchlist_monitor.py, replace the sequential analysis loop:
from orchestrator.session_orchestrator import run_parallel_watchlist_scan
from orchestrator.managed_agents import get_or_create_agents

agent_ids = get_or_create_agents()
results   = run_parallel_watchlist_scan(
    tickers=watchlist_tickers,
    agent_id=agent_ids["analysis"],
    max_concurrency=5,
)

for r in results:
    if "error" in r:
        print(f"[monitor] {r['ticker']} scan failed: {r['error']}", file=sys.stderr)
    else:
        # process r["analysis"] as before
        ...
```

### Code integration points

**Existing direct calls that can remain unchanged (Phase 4 does not require
migrating these):**

- `run_analysis()` in the `analyze` intent — still works; session enrichment
  is optional for single-ticker queries from Teams.
- `risk_agent.evaluate_proposal()` — still used by the portfolio optimizer and
  watchlist monitor. The session-based risk gate is additive, not a replacement.
- `journal_agent.sync_closed_trades()` — unchanged; it feeds the vector store
  via the Phase 1 integration.

**Session IDs for follow-up turns:**

The `session_id` returned by `run_analysis_session()` and `run_risk_session()`
can be used for follow-up messages in a future conversational interface:

```python
# Not yet wired into router.py — future Phase 5 enhancement:
analysis = run_analysis_session(ticker, agent_id, vector_ctx)
session_id = analysis["session_id"]

# Follow-up in the same session context:
followup = client.beta.sessions.create(
    session_id=session_id,
    messages=[{"role": "user", "content": "What's the stop-loss level?"}],
    extra_headers={"anthropic-beta": _BETA_HEADER},
)
```

### Verify

**End-to-end pipeline test:**

```bash
python orchestrator/session_orchestrator.py --ticker AAPL --qty 5 --side buy
```

Check that the output contains:
- A non-empty `analysis` field (the managed analysis agent responded)
- A valid `verdict` (APPROVED / RESIZE / BLOCK / ESCALATE)
- `vector_used > 0` if there are closed trades in the SQLite DB
- `total_tokens > 0`

**Parallel scan benchmark:**

```bash
time python orchestrator/session_orchestrator.py --watchlist AAPL NVDA MSFT AMD TSLA
```

With `max_concurrency=5` and no rate-limit hits, five tickers should complete
in roughly the same wall-clock time as a single ticker scan, not 5x longer.

**Router integration smoke test:**

```bash
# Start the MCP server and send a trade intent through the full stack:
python -m orchestrator.router  # (if you have a __main__ test block)
# or hit the HTTP endpoint:
curl -X POST http://localhost:8080/agent/message \
  -H "Content-Type: application/json" \
  -d '{"text": "Trade AAPL", "user_id": "test-user"}'
```

---

## Reference: Environment Variables

| Variable | Required | Default | Notes |
|----------|----------|---------|-------|
| `ANTHROPIC_API_KEY` | Yes | — | All Claude calls |
| `OPENAI_API_KEY` | No | — | text-embedding-3-small; falls back to chromadb default |
| `DB_PATH` | No | `~/Library/.../trading_memory.db` | Override SQLite path |
| `RISK_MAX_POSITION_PCT` | No | `0.05` | 5% position limit |
| `RISK_MAX_SECTOR_CONC_PCT` | No | `0.25` | 25% sector limit |
| `RISK_DAILY_LOSS_HALT` | No | `-0.02` | -2% circuit breaker |

## Reference: ChromaDB Collection Schemas

### trade_memories

Embedded text format:
```
Trade: BUY AAPL | Sector: Technology
Entry RSI: 28.5 | EMA signal: bullish
Entry: $175.00 on 2025-01-10 | Exit: $185.00 on 2025-01-20
Hold: 10 days | P&L: $100.0 (5.71%)
Thesis: RSI oversold, strong earnings momentum
```

Metadata keys: `ticker`, `side`, `sector`, `entry_rsi`, `ema_signal`,
`outcome_pnl`, `outcome_pct`, `hold_days`, `entry_date`, `exit_date`, `order_id`

### market_knowledge

Embedded text format:
```
Ticker: AAPL
Date: 2025-02-01
Headline: Apple beats Q1 earnings estimates

[article body, truncated to 2000 chars]
```

Metadata keys: `ticker`, `title`, `date`

### risk_decisions

Embedded text format:
```
Risk decision: ESCALATE for NVDA
Sector: Technology | Rule: 4 | Reason: correlation_guard
Equity at time: $50,000.00
Narrative: NVDA is correlated with AMD which you hold; adding both amplifies directional risk.
```

Metadata keys: `ticker`, `verdict`, `sector`, `rule`, `reason`, `timestamp`

## Reference: Quick Commands

```bash
# Phase 1 — Set up vector DB
pip install chromadb
python scripts/setup_vector_db.py

# Phase 1 — Re-backfill after closing new trades
python scripts/setup_vector_db.py --skip-backfill  # re-init only
python -c "from orchestrator.vector_store import backfill_from_sqlite; print(backfill_from_sqlite())"

# Phase 2 — Test vector queries
python orchestrator/vector_store.py

# Phase 3 — Register agents (one time)
pip install -U "anthropic>=0.92.0"
python scripts/register_agents.py

# Phase 3 — View current registry
python scripts/register_agents.py --show

# Phase 4 — Test single trade pipeline
python orchestrator/session_orchestrator.py --ticker AAPL --qty 5 --side buy

# Phase 4 — Test parallel watchlist scan
python orchestrator/session_orchestrator.py --watchlist AAPL NVDA MSFT

# Phase 4 — Test managed agents module
python orchestrator/managed_agents.py
```
