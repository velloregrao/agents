"""
orchestrator/vector_store.py

ChromaDB-backed vector store for Stock Copilot.

Three collections:
  trade_memories    — closed trade records (entry conditions, outcome)
  market_knowledge  — news articles indexed by ticker + date
  risk_decisions    — BLOCK / ESCALATE decisions with their narrative

Embeddings:
  Primary:  OpenAI text-embedding-3-small (if OPENAI_API_KEY is set)
  Fallback: ChromaDB default (sentence-transformers, free, local)

Collection storage: ~/.chromadb/stock_copilot/

Public API:
    initialize_collections() -> None
    embed_closed_trade(trade: dict) -> str
    query_similar_trades(ticker, rsi, side, n=5) -> list[dict]
    embed_news_article(ticker, title, body, date) -> str
    query_market_knowledge(ticker, query, n=5) -> list[dict]
    embed_risk_decision(ticker, verdict, narrative, context) -> str
    query_similar_risk_decisions(ticker, sector, n=3) -> list[dict]
    backfill_from_sqlite() -> dict
"""

from __future__ import annotations

import os
import sys
import json
import hashlib
from pathlib import Path
from datetime import datetime

# ── Path bootstrap ─────────────────────────────────────────────────────────────
_AGENTS_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_AGENTS_ROOT / "stock-analysis-agent" / "src"))

from dotenv import load_dotenv
load_dotenv(_AGENTS_ROOT / "stock-analysis-agent" / ".env")

# ── Model constants ────────────────────────────────────────────────────────────
SONNET = "claude-sonnet-4-6"
HAIKU  = "claude-haiku-4-5-20251001"

# ── ChromaDB setup ─────────────────────────────────────────────────────────────
_CHROMA_PATH = Path.home() / ".chromadb" / "stock_copilot"

try:
    import chromadb
    from chromadb.config import Settings
    _CHROMA_AVAILABLE = True
except ImportError:
    _CHROMA_AVAILABLE = False
    print(
        "[vector_store] chromadb not installed — run: pip install chromadb",
        file=sys.stderr,
    )

# ── Embedding function ─────────────────────────────────────────────────────────
# Use OpenAI text-embedding-3-small if OPENAI_API_KEY is set;
# otherwise fall through to ChromaDB's default embedding function.

def _get_embedding_function():
    """Return the best available embedding function."""
    openai_key = os.getenv("OPENAI_API_KEY")
    if openai_key:
        try:
            from chromadb.utils.embedding_functions import OpenAIEmbeddingFunction
            return OpenAIEmbeddingFunction(
                api_key=openai_key,
                model_name="text-embedding-3-small",
            )
        except Exception as exc:
            print(
                f"[vector_store] OpenAI embedding unavailable: {exc} — using default",
                file=sys.stderr,
            )
    # Default: chromadb's local sentence-transformers model
    try:
        from chromadb.utils.embedding_functions import DefaultEmbeddingFunction
        return DefaultEmbeddingFunction()
    except Exception:
        return None


# ── Client singleton ───────────────────────────────────────────────────────────

_client: "chromadb.Client | None" = None

def _get_client() -> "chromadb.Client":
    global _client
    if _client is None:
        if not _CHROMA_AVAILABLE:
            raise RuntimeError(
                "chromadb is not installed. Run: pip install chromadb"
            )
        _CHROMA_PATH.mkdir(parents=True, exist_ok=True)
        _client = chromadb.PersistentClient(path=str(_CHROMA_PATH))
    return _client


# ── Collection names ───────────────────────────────────────────────────────────

_COLLECTION_TRADE_MEMORIES   = "trade_memories"
_COLLECTION_MARKET_KNOWLEDGE = "market_knowledge"
_COLLECTION_RISK_DECISIONS   = "risk_decisions"


# ── initialize_collections ────────────────────────────────────────────────────

def initialize_collections() -> None:
    """
    Create (or open) the three ChromaDB collections.
    Safe to call repeatedly — get_or_create_collection is idempotent.
    """
    client  = _get_client()
    emb_fn  = _get_embedding_function()
    kwargs  = {"embedding_function": emb_fn} if emb_fn else {}

    for name in (
        _COLLECTION_TRADE_MEMORIES,
        _COLLECTION_MARKET_KNOWLEDGE,
        _COLLECTION_RISK_DECISIONS,
    ):
        client.get_or_create_collection(name=name, **kwargs)
        print(f"[vector_store] collection ready: {name}", flush=True)


def _get_collection(name: str):
    """Return a collection, creating it if needed."""
    client = _get_client()
    emb_fn = _get_embedding_function()
    kwargs = {"embedding_function": emb_fn} if emb_fn else {}
    return client.get_or_create_collection(name=name, **kwargs)


# ── Helper: stable doc ID ─────────────────────────────────────────────────────

def _make_id(*parts: str) -> str:
    """Generate a stable, collision-resistant document ID from string parts."""
    raw = "|".join(str(p) for p in parts)
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


# ── trade_memories collection ─────────────────────────────────────────────────

def embed_closed_trade(trade: dict) -> str:
    """
    Embed a closed trade record into the trade_memories collection.

    Expected trade dict fields (all optional except ticker / side):
        ticker, side, entry_rsi, entry_ema_signal (derived), thesis_text,
        reasoning, outcome_pnl (pnl), outcome_pct (pnl_pct), hold_days,
        entry_date, exit_date, entry_price, exit_price, sector, order_id

    Returns:
        doc_id  (str) — stable SHA256 derived from order_id + ticker + entry_date
    """
    ticker      = (trade.get("ticker") or "UNKNOWN").upper()
    side        = (trade.get("side")   or "BUY").upper()
    entry_rsi   = trade.get("entry_rsi")
    pnl         = trade.get("pnl")       or trade.get("outcome_pnl")
    pnl_pct     = trade.get("pnl_pct")   or trade.get("outcome_pct")
    hold_days   = trade.get("hold_days")
    reasoning   = trade.get("reasoning") or trade.get("thesis_text") or ""
    sector      = trade.get("sector")    or "Unknown"
    order_id    = trade.get("order_id")  or ""
    entry_date  = trade.get("entry_date") or ""
    exit_date   = trade.get("exit_date")  or ""
    entry_price = trade.get("entry_price")
    exit_price  = trade.get("exit_price")

    # Derive ema_signal heuristic from pnl direction when not stored
    if entry_rsi and pnl is not None:
        ema_signal = "bullish" if float(pnl) >= 0 else "bearish"
    else:
        ema_signal = "unknown"

    # Build embeddable text document
    doc = (
        f"Trade: {side} {ticker} | Sector: {sector}\n"
        f"Entry RSI: {entry_rsi} | EMA signal: {ema_signal}\n"
        f"Entry: ${entry_price} on {entry_date} | "
        f"Exit: ${exit_price} on {exit_date}\n"
        f"Hold: {hold_days} days | "
        f"P&L: ${pnl} ({pnl_pct}%)\n"
        f"Thesis: {reasoning}"
    )

    metadata = {
        "ticker":      ticker,
        "side":        side,
        "sector":      sector,
        "entry_rsi":   float(entry_rsi) if entry_rsi is not None else -1.0,
        "ema_signal":  ema_signal,
        "outcome_pnl": float(pnl)     if pnl     is not None else 0.0,
        "outcome_pct": float(pnl_pct) if pnl_pct is not None else 0.0,
        "hold_days":   int(hold_days)  if hold_days is not None else 0,
        "entry_date":  entry_date,
        "exit_date":   exit_date,
        "order_id":    order_id,
    }

    doc_id = _make_id(order_id or ticker, entry_date, side)
    col = _get_collection(_COLLECTION_TRADE_MEMORIES)
    col.upsert(documents=[doc], metadatas=[metadata], ids=[doc_id])
    return doc_id


def query_similar_trades(
    ticker: str,
    rsi: float,
    side: str,
    n: int = 5,
) -> list[dict]:
    """
    Retrieve the n most similar historical trades to the current setup.

    Query text is constructed to match the embedding format used in
    embed_closed_trade().

    Returns:
        List of dicts with keys: doc_id, document, metadata, distance
    """
    query_text = (
        f"Trade: {side.upper()} {ticker.upper()} | "
        f"Entry RSI: {rsi:.1f} | EMA signal: unknown"
    )
    col = _get_collection(_COLLECTION_TRADE_MEMORIES)

    try:
        results = col.query(
            query_texts=[query_text],
            n_results=min(n, col.count() or 1),
            include=["documents", "metadatas", "distances"],
        )
    except Exception as exc:
        print(f"[vector_store] query_similar_trades error: {exc}", file=sys.stderr)
        return []

    out = []
    ids        = results.get("ids",        [[]])[0]
    docs       = results.get("documents",  [[]])[0]
    metas      = results.get("metadatas",  [[]])[0]
    distances  = results.get("distances",  [[]])[0]

    for doc_id, doc, meta, dist in zip(ids, docs, metas, distances):
        out.append({"doc_id": doc_id, "document": doc, "metadata": meta, "distance": dist})
    return out


# ── market_knowledge collection ───────────────────────────────────────────────

def embed_news_article(
    ticker: str,
    title: str,
    body: str,
    date: str,
) -> str:
    """
    Embed a news article into the market_knowledge collection.

    Args:
        ticker: Stock symbol this article is about
        title:  Article headline
        body:   Full article body (will be truncated to 2000 chars to stay within limits)
        date:   Publication date (ISO string preferred)

    Returns:
        doc_id (str)
    """
    ticker = ticker.upper()
    body   = (body or "")[:2000]

    doc = f"Ticker: {ticker}\nDate: {date}\nHeadline: {title}\n\n{body}"
    metadata = {
        "ticker": ticker,
        "title":  title[:200],  # ChromaDB metadata values have length limits
        "date":   date,
    }

    doc_id = _make_id(ticker, date, title[:80])
    col = _get_collection(_COLLECTION_MARKET_KNOWLEDGE)
    col.upsert(documents=[doc], metadatas=[metadata], ids=[doc_id])
    return doc_id


def query_market_knowledge(
    ticker: str,
    query: str,
    n: int = 5,
) -> list[dict]:
    """
    Retrieve the n most relevant news articles for a given ticker and query.

    Returns:
        List of dicts with keys: doc_id, document, metadata, distance
    """
    query_text = f"Ticker: {ticker.upper()}\n{query}"
    col = _get_collection(_COLLECTION_MARKET_KNOWLEDGE)

    try:
        results = col.query(
            query_texts=[query_text],
            n_results=min(n, col.count() or 1),
            where={"ticker": ticker.upper()},
            include=["documents", "metadatas", "distances"],
        )
    except Exception as exc:
        # Fall back without the where filter (collection may be empty or filter fails)
        try:
            results = col.query(
                query_texts=[query_text],
                n_results=min(n, max(col.count(), 1)),
                include=["documents", "metadatas", "distances"],
            )
        except Exception as exc2:
            print(f"[vector_store] query_market_knowledge error: {exc2}", file=sys.stderr)
            return []

    out = []
    ids       = results.get("ids",       [[]])[0]
    docs      = results.get("documents", [[]])[0]
    metas     = results.get("metadatas", [[]])[0]
    distances = results.get("distances", [[]])[0]

    for doc_id, doc, meta, dist in zip(ids, docs, metas, distances):
        out.append({"doc_id": doc_id, "document": doc, "metadata": meta, "distance": dist})
    return out


# ── risk_decisions collection ─────────────────────────────────────────────────

def embed_risk_decision(
    ticker: str,
    verdict: str,
    narrative: str,
    context: dict,
) -> str:
    """
    Embed a BLOCK or ESCALATE risk decision into the risk_decisions collection.

    Args:
        ticker:    Stock symbol
        verdict:   "BLOCK" | "ESCALATE" | "RESIZE" | "APPROVED"
        narrative: Sonnet-generated plain-English explanation
        context:   Dict of rule_number, reason, equity, sector, etc.

    Returns:
        doc_id (str)
    """
    ticker  = ticker.upper()
    sector  = (context.get("sector") or context.get("ticker_sector") or "Unknown")
    rule    = context.get("rule", 0)
    reason  = context.get("reason", "")
    equity  = context.get("equity", 0)
    ts      = datetime.utcnow().isoformat()

    doc = (
        f"Risk decision: {verdict} for {ticker}\n"
        f"Sector: {sector} | Rule: {rule} | Reason: {reason}\n"
        f"Equity at time: ${equity:,.2f}\n"
        f"Narrative: {narrative}"
    )

    metadata = {
        "ticker":    ticker,
        "verdict":   verdict,
        "sector":    sector,
        "rule":      int(rule),
        "reason":    reason,
        "timestamp": ts,
    }

    doc_id = _make_id(ticker, verdict, ts)
    col = _get_collection(_COLLECTION_RISK_DECISIONS)
    col.upsert(documents=[doc], metadatas=[metadata], ids=[doc_id])
    return doc_id


def query_similar_risk_decisions(
    ticker: str,
    sector: str,
    n: int = 3,
) -> list[dict]:
    """
    Retrieve the n most relevant historical risk decisions for a given ticker + sector.

    Returns:
        List of dicts with keys: doc_id, document, metadata, distance
    """
    query_text = (
        f"Risk decision for {ticker.upper()} in sector {sector}"
    )
    col = _get_collection(_COLLECTION_RISK_DECISIONS)

    try:
        results = col.query(
            query_texts=[query_text],
            n_results=min(n, col.count() or 1),
            include=["documents", "metadatas", "distances"],
        )
    except Exception as exc:
        print(f"[vector_store] query_similar_risk_decisions error: {exc}", file=sys.stderr)
        return []

    out = []
    ids       = results.get("ids",       [[]])[0]
    docs      = results.get("documents", [[]])[0]
    metas     = results.get("metadatas", [[]])[0]
    distances = results.get("distances", [[]])[0]

    for doc_id, doc, meta, dist in zip(ids, docs, metas, distances):
        out.append({"doc_id": doc_id, "document": doc, "metadata": meta, "distance": dist})
    return out


# ── backfill_from_sqlite ──────────────────────────────────────────────────────

def backfill_from_sqlite() -> dict:
    """
    Read all CLOSED trades from the existing SQLite trading_memory.db and
    embed them into the trade_memories collection.

    Skips records that are already in ChromaDB (upsert is idempotent).

    Returns:
        {
            "total":    int  — total closed trades found in SQLite,
            "embedded": int  — new records embedded this run,
            "skipped":  int  — records that raised errors,
            "errors":   list — error details,
        }
    """
    from stock_agent.memory import DB_PATH
    import sqlite3

    print(f"[vector_store] backfill from SQLite: {DB_PATH}", flush=True)

    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM trades
            WHERE status = 'CLOSED'
            ORDER BY exit_date DESC
        """)
        trades = [dict(row) for row in cursor.fetchall()]
        conn.close()
    except Exception as exc:
        return {"total": 0, "embedded": 0, "skipped": 0, "errors": [str(exc)]}

    total    = len(trades)
    embedded = 0
    skipped  = 0
    errors   = []

    for trade in trades:
        try:
            embed_closed_trade(trade)
            embedded += 1
        except Exception as exc:
            skipped += 1
            errors.append({"ticker": trade.get("ticker"), "error": str(exc)})

    print(
        f"[vector_store] backfill complete — "
        f"{total} total, {embedded} embedded, {skipped} skipped",
        flush=True,
    )
    return {
        "total":    total,
        "embedded": embedded,
        "skipped":  skipped,
        "errors":   errors,
    }


# ── Standalone test ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=== vector_store.py standalone test ===\n")

    # 1. Initialize collections
    print("1. Initializing collections...")
    initialize_collections()

    # 2. Embed a synthetic trade
    print("\n2. Embedding a synthetic closed trade...")
    synthetic = {
        "order_id":    "test-001",
        "ticker":      "AAPL",
        "side":        "BUY",
        "sector":      "Technology",
        "entry_rsi":   28.5,
        "entry_price": 175.00,
        "exit_price":  185.00,
        "entry_date":  "2025-01-10",
        "exit_date":   "2025-01-20",
        "hold_days":   10,
        "pnl":         100.00,
        "pnl_pct":     5.71,
        "reasoning":   "RSI oversold, strong earnings momentum",
    }
    doc_id = embed_closed_trade(synthetic)
    print(f"   doc_id: {doc_id}")

    # 3. Query similar trades
    print("\n3. Querying similar trades (AAPL, RSI=30, BUY)...")
    results = query_similar_trades("AAPL", 30.0, "BUY", n=3)
    for r in results:
        print(f"   [{r['distance']:.3f}] {r['document'][:80]}...")

    # 4. Embed a news article
    print("\n4. Embedding a news article...")
    aid = embed_news_article(
        ticker="AAPL",
        title="Apple beats Q1 earnings estimates",
        body="Apple Inc. reported Q1 earnings of $2.18 per share, beating estimates...",
        date="2025-02-01",
    )
    print(f"   doc_id: {aid}")

    # 5. Embed a risk decision
    print("\n5. Embedding a risk decision...")
    rid = embed_risk_decision(
        ticker="NVDA",
        verdict="ESCALATE",
        narrative="NVDA is correlated with AMD which you hold; adding both amplifies directional risk.",
        context={"rule": 4, "reason": "correlation_guard", "equity": 50000, "sector": "Technology"},
    )
    print(f"   doc_id: {rid}")

    # 6. Backfill from SQLite
    print("\n6. Backfilling from SQLite...")
    stats = backfill_from_sqlite()
    print(f"   total={stats['total']}, embedded={stats['embedded']}, skipped={stats['skipped']}")

    print("\n=== test complete ===")
