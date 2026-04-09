"""
orchestrator/managed_agents.py

One-time agent registration using Anthropic v0.92.0 client.beta.agents API.

Three managed agents are registered:
  analysis_agent   — technical + fundamental analysis, pulls vector context
  risk_agent       — generator-critic risk gate with rule enforcement
  portfolio_agent  — portfolio optimization, rebalancing, P&L monitoring

Registration is idempotent:
  get_or_create_agents() loads the registry if it exists, creates agents
  only when they are missing, and always returns the current IDs.

Registry file: /Users/velloregrao/Projects/agents/.agent_registry.json

Usage:
    from orchestrator.managed_agents import get_or_create_agents
    ids = get_or_create_agents()
    # ids == {"analysis": "...", "risk": "...", "portfolio": "..."}
"""

from __future__ import annotations

import os
import sys
import json
from pathlib import Path

# ── Path bootstrap ─────────────────────────────────────────────────────────────
_AGENTS_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_AGENTS_ROOT / "stock-analysis-agent" / "src"))

from dotenv import load_dotenv
load_dotenv(_AGENTS_ROOT / "stock-analysis-agent" / ".env")

import anthropic

# ── Model constants ────────────────────────────────────────────────────────────
SONNET = "claude-sonnet-4-6"
HAIKU  = "claude-haiku-4-5-20251001"

# ── Registry path ──────────────────────────────────────────────────────────────
_REGISTRY_PATH = _AGENTS_ROOT / ".agent_registry.json"

# ── Beta flag required by managed-agents API ─────────────────────────────────
_BETA_FLAG = "managed-agents-2026-04-01"

# ── MCP server names (must match mcp-servers/ directory names) ────────────────
_MCP_SERVERS = ["memory", "news", "orchestrator", "portfolio", "stock-data"]


# ── Client factory ─────────────────────────────────────────────────────────────

def _get_client() -> anthropic.Anthropic:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. "
            "Add it to stock-analysis-agent/.env or export it."
        )
    return anthropic.Anthropic(api_key=api_key)


# ── System prompts ─────────────────────────────────────────────────────────────

_ANALYSIS_SYSTEM = """You are a professional stock analyst powered by Claude.

Your responsibilities:
1. Retrieve technical indicators (RSI, EMA, VWAP, momentum) via stock-data tools
2. Search for recent news sentiment using the news tools
3. Recall similar historical trades using memory tools
4. Synthesise all signals into a structured analysis covering:
   - Company overview and current price
   - Technical analysis (RSI, EMA crossover signal, momentum score)
   - News sentiment and market context
   - Historical precedent from similar trades in memory
   - Summary verdict (bullish / neutral / bearish) with confidence level
   - Suggested entry price, position size, and stop-loss

When vector context (similar_trades) is provided in the system prompt prefix,
always reference those historical outcomes to calibrate your confidence.

Present numbers clearly. Be direct and opinionated.
This is for informational purposes only and not financial advice."""

_RISK_SYSTEM = """You are a risk manager enforcing a strict generator-critic pattern.

Your role is to evaluate every trade proposal against four rules in order:

Rule 1 — Daily loss circuit breaker
  BLOCK all trading if the portfolio is down more than RISK_DAILY_LOSS_HALT on the day.

Rule 2 — Position size limit
  No single position > RISK_MAX_POSITION_PCT of total equity.
  RESIZE if over; BLOCK if max affordable qty is zero.

Rule 3 — Sector concentration
  No GICS sector > RISK_MAX_SECTOR_CONC_PCT of total equity.
  ESCALATE (do not block) so a human can review.

Rule 4 — Correlation guard
  ESCALATE if the proposed ticker is in a known correlated pair with a held stock.

Verdicts (return exactly one):
  APPROVED  — execute with adjusted_qty
  RESIZE    — reduce qty to fit position limit, execute
  BLOCK     — do not execute, return reason
  ESCALATE  — post Teams card, await human approval

Always generate a plain-English 2-3 sentence narrative explaining the verdict.
Reference specific dollar amounts and percentages. Use language a non-technical
trader would understand. Do not start with "I"."""

_PORTFOLIO_SYSTEM = """You are a portfolio optimizer and monitor for a US equities trading account.

Your responsibilities:
1. Fetch current positions and account balance via portfolio tools
2. Compare current allocations against target allocations (provided in context)
3. Identify positions with drift > threshold that need rebalancing
4. Generate a ranked rebalancing trade list: sells first, then buys
5. Each trade in the plan must still pass through the risk gate before execution

When monitoring open positions:
- Flag positions where thesis has invalidated (RSI overbought after BUY, etc.)
- Flag positions with hold time exceeding the expected hold window
- Flag P&L outliers (significant gains to protect or losses to cut)

Output a structured plan:
  - Current vs target allocation per position
  - Drift magnitude
  - Suggested trades (side, qty, rationale)
  - Expected cash flow after rebalancing
  - Total plan risk summary

Always require human approval before executing any rebalancing trades.
This is for informational purposes only and not financial advice."""


# ── Agent registration helpers ────────────────────────────────────────────────

def _create_agent(
    client: anthropic.Anthropic,
    name: str,
    system_prompt: str,
    tools: list[dict] | None = None,
) -> str:
    """
    Register a single managed agent via client.beta.agents.create().

    The beta header is injected via the extra_headers parameter.

    Returns:
        agent_id (str)
    """
    kwargs: dict = {
        "name":   name,
        "model":  SONNET,
        "system": system_prompt,
    }
    if tools:
        kwargs["tools"] = tools

    try:
        agent = client.beta.agents.create(
            **kwargs,
            betas=[_BETA_FLAG],
        )
        return agent.id
    except AttributeError:
        # SDK version doesn't have client.beta.agents — provide a clear error
        raise RuntimeError(
            "client.beta.agents is not available in this SDK version. "
            "Upgrade to anthropic>=0.92.0: pip install -U anthropic"
        )


def _mcp_tools_list(server_names: list[str] | None = None) -> list[dict]:
    """
    Build the tools list for managed agents using the mcp_toolset type.
    Each entry references a named MCP server configured in the environment.

    Args:
        server_names: Subset of MCP servers to include. Defaults to all.
    """
    names = server_names or _MCP_SERVERS
    return [
        {"type": "mcp_toolset", "mcp_server_name": name}
        for name in names
    ]


# ── Public registration functions ─────────────────────────────────────────────

def register_analysis_agent() -> str:
    """
    Register the analysis agent with Anthropic and save its ID to the registry.

    Returns:
        agent_id (str)
    """
    client   = _get_client()
    agent_id = _create_agent(
        client,
        name="stock-copilot-analysis",
        system_prompt=_ANALYSIS_SYSTEM,
        # MCP tools are local stdio servers — invoked via session_orchestrator,
        # not via the managed-agents tool registry (which requires URL servers)
        tools=None,
    )
    _patch_registry("analysis", agent_id)
    print(f"[managed_agents] registered analysis agent: {agent_id}", flush=True)
    return agent_id


def register_risk_agent() -> str:
    """
    Register the risk agent with Anthropic and save its ID to the registry.

    Returns:
        agent_id (str)
    """
    client   = _get_client()
    agent_id = _create_agent(
        client,
        name="stock-copilot-risk",
        system_prompt=_RISK_SYSTEM,
        tools=None,
    )
    _patch_registry("risk", agent_id)
    print(f"[managed_agents] registered risk agent: {agent_id}", flush=True)
    return agent_id


def register_portfolio_agent() -> str:
    """
    Register the portfolio agent with Anthropic and save its ID to the registry.

    Returns:
        agent_id (str)
    """
    client   = _get_client()
    agent_id = _create_agent(
        client,
        name="stock-copilot-portfolio",
        system_prompt=_PORTFOLIO_SYSTEM,
        tools=None,
    )
    _patch_registry("portfolio", agent_id)
    print(f"[managed_agents] registered portfolio agent: {agent_id}", flush=True)
    return agent_id


def register_all_agents() -> dict:
    """
    Register all three agents and return their IDs.

    Returns:
        {"analysis": id, "risk": id, "portfolio": id}
    """
    return {
        "analysis":  register_analysis_agent(),
        "risk":      register_risk_agent(),
        "portfolio": register_portfolio_agent(),
    }


# ── Registry I/O ──────────────────────────────────────────────────────────────

def _patch_registry(key: str, agent_id: str) -> None:
    """Write or update a single key in the registry JSON file."""
    registry = load_agent_registry()
    registry[key] = agent_id
    _REGISTRY_PATH.write_text(json.dumps(registry, indent=2))


def load_agent_registry() -> dict:
    """
    Load the agent registry from disk.

    Returns:
        Dict mapping role name to agent_id. Empty dict if registry doesn't exist.
    """
    if not _REGISTRY_PATH.exists():
        return {}
    try:
        return json.loads(_REGISTRY_PATH.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        print(
            f"[managed_agents] warning: could not read registry: {exc}",
            file=sys.stderr,
        )
        return {}


def get_or_create_environment() -> str:
    """
    Create (or retrieve from registry) a cloud environment for running sessions.

    Sessions require an environment_id. This creates one named
    'stock-copilot-env' and caches its ID in the registry.

    Returns:
        environment_id (str)
    """
    registry = load_agent_registry()
    if "environment_id" in registry:
        return registry["environment_id"]

    client = _get_client()
    env = client.beta.environments.create(
        name="stock-copilot-env",
        description="Stock Copilot analysis + trading environment",
        betas=[_BETA_FLAG],
    )
    env_id = env.id
    _patch_registry("environment_id", env_id)
    print(f"[managed_agents] created environment: {env_id}", flush=True)
    return env_id


def get_or_create_agents() -> dict:
    """
    Idempotent entry point — loads the registry if it exists, registers any
    missing agents, and returns a dict of all three agent IDs plus environment_id.

    Returns:
        {"analysis": id, "risk": id, "portfolio": id, "environment_id": id}

    Safe to call multiple times — only creates what is absent.
    """
    registry = load_agent_registry()
    missing  = {"analysis", "risk", "portfolio"} - set(registry.keys())

    if not missing and "environment_id" in registry:
        print("[managed_agents] all agents already registered — using registry", flush=True)
        return registry

    # Create environment first if missing
    if "environment_id" not in registry:
        get_or_create_environment()

    if missing:
        print(f"[managed_agents] registering missing agents: {missing}", flush=True)
        for role in missing:
            if role == "analysis":
                register_analysis_agent()
            elif role == "risk":
                register_risk_agent()
            elif role == "portfolio":
                register_portfolio_agent()

    return load_agent_registry()


# ── Standalone test ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=== managed_agents.py standalone test ===\n")

    print("Calling get_or_create_agents()...")
    try:
        ids = get_or_create_agents()
        print(f"\nAgent registry:")
        for role, agent_id in ids.items():
            print(f"  {role:12s} → {agent_id}")
        print(f"\nRegistry saved to: {_REGISTRY_PATH}")
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        print(
            "\nIf the managed-agents beta is not yet available on your account, "
            "the agent IDs can be manually set in .agent_registry.json.",
            file=sys.stderr,
        )
