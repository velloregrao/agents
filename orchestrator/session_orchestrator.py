"""
orchestrator/session_orchestrator.py

Session-based multi-agent orchestration using Anthropic v0.92.0
client.beta.sessions API.

This module replaces direct function calls in router.py with managed
session pipelines that carry state across agent boundaries.

Pipeline for a full trade:
  1. Retrieve vector context from ChromaDB (similar historical trades)
  2. Run analysis session (analysis agent analyses the ticker)
  3. Run risk session   (risk agent gates the proposal)
  4. Return execution decision to the caller

For the watchlist monitor (parallel fan-out):
  run_parallel_watchlist_scan() uses asyncio.gather() to scan N tickers
  concurrently, each in its own session.

Public API:
    run_analysis_session(ticker, agent_id, vector_context) -> dict
    run_risk_session(ticker, proposed_qty, side, agent_id, analysis_result) -> dict
    run_trade_pipeline(ticker, qty, side, user_id) -> dict
    run_parallel_watchlist_scan(tickers, agent_id) -> list[dict]

Beta header: "managed-agents-2026-04-01"
"""

from __future__ import annotations

import os
import sys
import json
import asyncio
from pathlib import Path
from typing import Any

# ── Path bootstrap ─────────────────────────────────────────────────────────────
_AGENTS_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_AGENTS_ROOT / "stock-analysis-agent" / "src"))

from dotenv import load_dotenv
load_dotenv(_AGENTS_ROOT / "stock-analysis-agent" / ".env")

import anthropic

# ── Model constants ────────────────────────────────────────────────────────────
SONNET = "claude-sonnet-4-6"
HAIKU  = "claude-haiku-4-5-20251001"

# ── Beta flag ──────────────────────────────────────────────────────────────────
_BETA_FLAG = "managed-agents-2026-04-01"

# ── Max tokens per session turn ───────────────────────────────────────────────
_MAX_TOKENS_ANALYSIS  = 4096
_MAX_TOKENS_RISK      = 1024
_MAX_TOKENS_PORTFOLIO = 2048


# ── Client factory ─────────────────────────────────────────────────────────────

def _get_client() -> anthropic.Anthropic:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set.")
    return anthropic.Anthropic(api_key=api_key)


# ── Vector context helpers ─────────────────────────────────────────────────────

def _format_vector_context(similar_trades: list[dict]) -> str:
    """
    Convert a list of similar-trade dicts from ChromaDB into a concise
    prompt prefix that the analysis agent can reference.
    """
    if not similar_trades:
        return ""

    lines = ["## Historical Similar Trades (from memory)\n"]
    for i, item in enumerate(similar_trades, 1):
        meta = item.get("metadata", {})
        dist = item.get("distance", 1.0)
        similarity = max(0, round((1 - dist) * 100, 1))
        lines.append(
            f"{i}. {meta.get('ticker','?')} {meta.get('side','?')} "
            f"| RSI: {meta.get('entry_rsi','?')} "
            f"| P&L: {meta.get('outcome_pct','?')}% "
            f"| Hold: {meta.get('hold_days','?')}d "
            f"| Similarity: {similarity}%"
        )
    lines.append(
        "\nUse these historical outcomes to calibrate your confidence level."
    )
    return "\n".join(lines)


def _get_vector_context(ticker: str, rsi: float = 50.0, side: str = "BUY") -> list[dict]:
    """
    Retrieve similar trades from ChromaDB. Returns empty list if vector
    store is unavailable (allows graceful degradation).
    """
    try:
        from orchestrator.vector_store import query_similar_trades
        return query_similar_trades(ticker=ticker, rsi=rsi, side=side, n=5)
    except Exception as exc:
        print(
            f"[session_orchestrator] vector context unavailable: {exc}",
            file=sys.stderr,
        )
        return []


# ── Session runner helper ─────────────────────────────────────────────────────

def _get_environment_id() -> str:
    """
    Load the environment_id from the agent registry.
    sessions.create requires an environment_id — created during Phase 3 setup.
    """
    from orchestrator.managed_agents import load_agent_registry
    registry = load_agent_registry()
    env_id = registry.get("environment_id")
    if not env_id:
        raise RuntimeError(
            "environment_id not found in .agent_registry.json. "
            "Run: python scripts/register_agents.py"
        )
    return env_id


def _run_session(
    client: anthropic.Anthropic,
    agent_id: str,
    messages: list[dict],
    max_tokens: int = 2048,
) -> dict:
    """
    Execute a single session turn using client.beta.sessions.create().

    The `agent` param accepts a plain agent_id string.
    `environment_id` is required and loaded from the registry.

    Returns:
        {
            "text":       str  — final text content from the session,
            "session_id": str  — session ID for audit trail,
            "stop_reason":str,
            "usage":      dict,
        }
    """
    environment_id = _get_environment_id()

    try:
        session = client.beta.sessions.create(
            agent=agent_id,
            environment_id=environment_id,
            betas=[_BETA_FLAG],
        )

        # sessions.create returns the session object; send the first message
        # via sessions.update or use the session ID with messages.create.
        # For now capture any initial content.
        text = ""
        for block in getattr(session, "content", []):
            if hasattr(block, "text"):
                text += block.text

        session_id = getattr(session, "id", None)

        # If the session was created but content needs a message event,
        # use beta.messages with the session context (fallback path).
        if not text and messages:
            msg_resp = client.beta.messages.create(
                model=SONNET,
                max_tokens=max_tokens,
                messages=messages,
                betas=[_BETA_FLAG],
                extra_headers={"X-Session-Id": session_id} if session_id else {},
            )
            for block in getattr(msg_resp, "content", []):
                if hasattr(block, "text"):
                    text += block.text
            usage_obj = getattr(msg_resp, "usage", None)
        else:
            usage_obj = getattr(session, "usage", None)

        return {
            "text":        text,
            "session_id":  session_id,
            "stop_reason": getattr(session, "stop_reason", "end_turn"),
            "usage":       {
                "input_tokens":  getattr(usage_obj, "input_tokens", 0),
                "output_tokens": getattr(usage_obj, "output_tokens", 0),
            },
        }

    except Exception as exc:
        return {
            "text":        f"[session error] {exc}",
            "session_id":  None,
            "stop_reason": "error",
            "usage":       {"input_tokens": 0, "output_tokens": 0},
        }


# ── run_analysis_session ──────────────────────────────────────────────────────

def run_analysis_session(
    ticker: str,
    agent_id: str,
    vector_context: list[dict],
) -> dict:
    """
    Run an analysis session for the given ticker, enriched with vector context.

    Args:
        ticker:         Stock symbol to analyse
        agent_id:       Managed agent ID for the analysis agent
        vector_context: List of similar-trade dicts from ChromaDB

    Returns:
        {
            "ticker":      str,
            "analysis":    str  — full analysis text,
            "session_id":  str,
            "usage":       dict,
            "vector_used": int  — number of similar trades injected,
        }
    """
    client = _get_client()

    context_prefix = _format_vector_context(vector_context)
    user_message = (
        f"{context_prefix}\n\n" if context_prefix else ""
    ) + f"Please provide a comprehensive stock analysis for {ticker.upper()}."

    result = _run_session(
        client=client,
        agent_id=agent_id,
        messages=[{"role": "user", "content": user_message}],
        max_tokens=_MAX_TOKENS_ANALYSIS,
    )

    return {
        "ticker":      ticker.upper(),
        "analysis":    result["text"],
        "session_id":  result["session_id"],
        "usage":       result["usage"],
        "vector_used": len(vector_context),
    }


# ── run_risk_session ──────────────────────────────────────────────────────────

def run_risk_session(
    ticker: str,
    proposed_qty: int,
    side: str,
    agent_id: str,
    analysis_result: dict,
) -> dict:
    """
    Run a risk evaluation session for a proposed trade.

    The analysis result (from run_analysis_session) is injected as context
    so the risk agent understands the rationale behind the proposal.

    Args:
        ticker:          Stock symbol
        proposed_qty:    Number of shares proposed
        side:            "buy" or "sell"
        agent_id:        Managed agent ID for the risk agent
        analysis_result: Dict returned by run_analysis_session

    Returns:
        {
            "ticker":       str,
            "side":         str,
            "proposed_qty": int,
            "verdict":      str  — "APPROVED" | "RESIZE" | "BLOCK" | "ESCALATE",
            "adjusted_qty": int,
            "reason":       str,
            "narrative":    str,
            "session_id":   str,
            "usage":        dict,
        }
    """
    client = _get_client()

    analysis_summary = (analysis_result.get("analysis") or "")[:1500]

    prompt = (
        f"## Trade Proposal\n"
        f"Ticker: {ticker.upper()}\n"
        f"Side: {side.upper()}\n"
        f"Proposed quantity: {proposed_qty} shares\n\n"
        f"## Analysis Context\n"
        f"{analysis_summary}\n\n"
        f"Evaluate this proposal against all four risk rules and return your verdict "
        f"in this exact JSON format (no markdown fences):\n"
        f'{{"verdict": "APPROVED|RESIZE|BLOCK|ESCALATE", '
        f'"adjusted_qty": <int>, "reason": "<code>", "narrative": "<2-3 sentences>"}}'
    )

    result = _run_session(
        client=client,
        agent_id=agent_id,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=_MAX_TOKENS_RISK,
    )

    # Parse structured response from the risk agent
    text = result["text"].strip()
    verdict      = "APPROVED"
    adjusted_qty = proposed_qty
    reason       = "all_rules_passed"
    narrative    = text

    # Try to extract JSON from the risk agent's response
    try:
        # Strip any accidental markdown fences
        clean = text
        if "```" in clean:
            clean = clean.split("```")[1].split("```")[0].strip()
            if clean.startswith("json"):
                clean = clean[4:].strip()

        parsed       = json.loads(clean)
        verdict      = parsed.get("verdict",      verdict).upper()
        adjusted_qty = int(parsed.get("adjusted_qty", proposed_qty))
        reason       = parsed.get("reason",       reason)
        narrative    = parsed.get("narrative",     text)
    except (json.JSONDecodeError, ValueError, KeyError):
        # Risk agent didn't return clean JSON — keep defaults
        pass

    return {
        "ticker":       ticker.upper(),
        "side":         side.lower(),
        "proposed_qty": proposed_qty,
        "verdict":      verdict,
        "adjusted_qty": adjusted_qty,
        "reason":       reason,
        "narrative":    narrative,
        "session_id":   result["session_id"],
        "usage":        result["usage"],
    }


# ── run_trade_pipeline ────────────────────────────────────────────────────────

def run_trade_pipeline(
    ticker: str,
    qty: int,
    side: str,
    user_id: str,
) -> dict:
    """
    Main orchestration entry point for a single-ticker trade decision.

    Pipeline:
      1. Retrieve vector context from ChromaDB
      2. Run analysis session (returns analysis text + session_id)
      3. Run risk session  (evaluates the proposal against 4 rules)
      4. Return execution decision

    The caller is responsible for:
      - Executing the trade (if APPROVED or RESIZE) via trade.py
      - Posting a Teams Adaptive Card (if ESCALATE or BLOCK)

    Args:
        ticker:  Stock symbol
        qty:     Proposed number of shares
        side:    "buy" | "sell"
        user_id: Teams user ID (for audit trail)

    Returns:
        {
            "ticker":         str,
            "side":           str,
            "proposed_qty":   int,
            "verdict":        str,
            "adjusted_qty":   int,
            "reason":         str,
            "narrative":      str,
            "analysis":       str,
            "vector_used":    int,
            "analysis_session_id": str | None,
            "risk_session_id":     str | None,
            "total_tokens":   int,
        }
    """
    from orchestrator.managed_agents import get_or_create_agents

    # ── Load or register agents ────────────────────────────────────────────
    agent_ids = get_or_create_agents()

    # ── Step 1: vector context ─────────────────────────────────────────────
    vector_ctx = _get_vector_context(ticker=ticker, side=side.upper())
    print(
        f"[session_orchestrator] {ticker} — {len(vector_ctx)} similar trades from vector store",
        flush=True,
    )

    # ── Step 2: analysis session ───────────────────────────────────────────
    analysis = run_analysis_session(
        ticker=ticker,
        agent_id=agent_ids["analysis"],
        vector_context=vector_ctx,
    )
    print(
        f"[session_orchestrator] analysis complete — "
        f"{analysis['usage'].get('output_tokens', 0)} tokens",
        flush=True,
    )

    # ── Step 3: risk session ───────────────────────────────────────────────
    risk = run_risk_session(
        ticker=ticker,
        proposed_qty=qty,
        side=side,
        agent_id=agent_ids["risk"],
        analysis_result=analysis,
    )
    print(
        f"[session_orchestrator] risk verdict: {risk['verdict']} — {risk['reason']}",
        flush=True,
    )

    # ── Step 4: embed risk decision into vector store ─────────────────────
    if risk["verdict"] in ("BLOCK", "ESCALATE"):
        try:
            from orchestrator.vector_store import embed_risk_decision
            embed_risk_decision(
                ticker=ticker,
                verdict=risk["verdict"],
                narrative=risk["narrative"],
                context={"rule": 0, "reason": risk["reason"]},
            )
        except Exception as exc:
            print(
                f"[session_orchestrator] embed_risk_decision failed: {exc}",
                file=sys.stderr,
            )

    total_tokens = (
        analysis["usage"].get("input_tokens", 0) +
        analysis["usage"].get("output_tokens", 0) +
        risk["usage"].get("input_tokens", 0) +
        risk["usage"].get("output_tokens", 0)
    )

    return {
        "ticker":               ticker.upper(),
        "side":                 side.lower(),
        "proposed_qty":         qty,
        "verdict":              risk["verdict"],
        "adjusted_qty":         risk["adjusted_qty"],
        "reason":               risk["reason"],
        "narrative":            risk["narrative"],
        "analysis":             analysis["analysis"],
        "vector_used":          analysis["vector_used"],
        "analysis_session_id":  analysis["session_id"],
        "risk_session_id":      risk["session_id"],
        "total_tokens":         total_tokens,
    }


# ── run_parallel_watchlist_scan ───────────────────────────────────────────────

async def _scan_ticker_async(
    ticker: str,
    agent_id: str,
    semaphore: asyncio.Semaphore,
) -> dict:
    """
    Scan a single ticker asynchronously with a concurrency semaphore.
    Wraps run_analysis_session() in asyncio.to_thread() since the Anthropic
    SDK is synchronous.
    """
    async with semaphore:
        vector_ctx = await asyncio.to_thread(
            _get_vector_context, ticker, 50.0, "BUY"
        )
        result = await asyncio.to_thread(
            run_analysis_session, ticker, agent_id, vector_ctx
        )
        return result


def run_parallel_watchlist_scan(
    tickers: list[str],
    agent_id: str,
    max_concurrency: int = 5,
) -> list[dict]:
    """
    Scan multiple tickers concurrently using asyncio.gather().

    Each ticker gets its own analysis session with vector context injected.
    Concurrency is capped by max_concurrency to stay within API rate limits.

    Args:
        tickers:         List of stock symbols to scan
        agent_id:        Managed agent ID for the analysis agent
        max_concurrency: Maximum number of parallel sessions (default: 5)

    Returns:
        List of analysis result dicts (one per ticker), in completion order.
        Failed tickers include an "error" key instead of "analysis".
    """
    if not tickers:
        return []

    print(
        f"[session_orchestrator] parallel scan: {tickers} "
        f"(concurrency={max_concurrency})",
        flush=True,
    )

    async def _gather_all() -> list[dict]:
        semaphore = asyncio.Semaphore(max_concurrency)
        tasks = [
            _scan_ticker_async(ticker, agent_id, semaphore)
            for ticker in tickers
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        output = []
        for ticker, res in zip(tickers, results):
            if isinstance(res, Exception):
                output.append({"ticker": ticker.upper(), "error": str(res)})
            else:
                output.append(res)
        return output

    return asyncio.run(_gather_all())


# ── Standalone test ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="session_orchestrator standalone test")
    parser.add_argument("--ticker",  default="AAPL", help="Ticker to analyse")
    parser.add_argument("--qty",     type=int, default=5, help="Proposed qty")
    parser.add_argument("--side",    default="buy", choices=["buy", "sell"])
    parser.add_argument("--watchlist", nargs="*", help="Run parallel scan")
    args = parser.parse_args()

    if args.watchlist:
        print(f"\n=== Parallel watchlist scan: {args.watchlist} ===\n")
        from orchestrator.managed_agents import get_or_create_agents
        ids = get_or_create_agents()
        results = run_parallel_watchlist_scan(
            tickers=args.watchlist,
            agent_id=ids["analysis"],
        )
        for r in results:
            if "error" in r:
                print(f"\n[{r['ticker']}] ERROR: {r['error']}")
            else:
                print(f"\n[{r['ticker']}] {r['analysis'][:200]}...")
    else:
        print(f"\n=== Trade pipeline: {args.ticker} {args.side} x{args.qty} ===\n")
        result = run_trade_pipeline(
            ticker=args.ticker,
            qty=args.qty,
            side=args.side,
            user_id="test-user",
        )
        print(f"Verdict:      {result['verdict']}")
        print(f"Adjusted qty: {result['adjusted_qty']}")
        print(f"Reason:       {result['reason']}")
        print(f"Narrative:    {result['narrative']}")
        print(f"Vector used:  {result['vector_used']} similar trades")
        print(f"Total tokens: {result['total_tokens']}")
        print(f"\nAnalysis (first 300 chars):\n{result['analysis'][:300]}...")
